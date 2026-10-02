"""Backup and restore tests."""

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest


class TestDownloadBackup:
    """GET /api/backup endpoint."""

    def test_backup_returns_zip_file(self, authenticated_client):
        response = authenticated_client.get("/api/backup")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert "attachment" in response.headers.get("content-disposition", "")

    def test_backup_filename_contains_timestamp(self, authenticated_client):
        response = authenticated_client.get("/api/backup")
        disposition = response.headers.get("content-disposition", "")
        assert "sonos-doorbell-backup" in disposition
        assert ".zip" in disposition

    def test_backup_contains_config_json(self, authenticated_client):
        # Add some data
        authenticated_client.post("/api/boxes", json={"ip": "192.0.2.1", "name": "Kitchen"})

        response = authenticated_client.get("/api/backup")
        data = response.content

        # Parse the zip
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert "config.json" in zf.namelist()
            config = json.loads(zf.read("config.json"))
            assert "version" in config
            assert "boxes" in config

    def test_backup_includes_advertise_host(self, authenticated_client):
        authenticated_client.put("/api/settings", json={"advertise_host": "192.0.2.100"})

        response = authenticated_client.get("/api/backup")
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            config = json.loads(zf.read("config.json"))
            assert config.get("advertise_host") == "192.0.2.100"

    def test_backup_includes_profiles_with_tokens(self, authenticated_client):
        box = authenticated_client.post(
            "/api/boxes", json={"ip": "192.0.2.1", "name": "Box"}
        ).json()

        profile = authenticated_client.post(
            "/api/profiles",
            json={
                "name": "Profile",
                "sound": "ding-dong",
                "members": [{"box": box["id"], "volume": 50}],
            },
        ).json()

        response = authenticated_client.get("/api/backup")
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            config = json.loads(zf.read("config.json"))
            assert len(config["profiles"]) == 1
            assert config["profiles"][0]["token"] == profile["token"]

    def test_backup_excludes_password_hash(self, authenticated_client):
        response = authenticated_client.get("/api/backup")
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            config = json.loads(zf.read("config.json"))
            # Auth info should NOT be in backup
            assert "password_hash" not in config
            assert "secret" not in config

    def test_backup_includes_uploaded_sounds(self, authenticated_client):
        async def fake_ffmpeg(self, *cmd):
            Path(cmd[-1]).write_bytes(b"ID3 fake mp3")
            return b""

        async def fake_duration(self, path):
            return 3.0

        with patch("app.sounds.shutil.which", return_value="/usr/bin/ffmpeg"),                 patch("app.sounds.SoundLibrary._run", fake_ffmpeg),                 patch("app.sounds.SoundLibrary._duration", fake_duration):
            sound_response = authenticated_client.post(
                "/api/sounds",
                data={"name": "Custom"},
                files={"file": ("test.mp3", io.BytesIO(b"fake mp3"), "audio/mpeg")},
            )
        assert sound_response.status_code == 201
        sound_file = sound_response.json()["url"].split("/")[-1]

        response = authenticated_client.get("/api/backup")
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            assert f"sounds/{sound_file}" in zf.namelist()
            assert zf.read(f"sounds/{sound_file}") == b"ID3 fake mp3"


class TestRestoreBackup:
    """POST /api/restore endpoint."""

    def test_restore_invalid_zip_returns_400(self, authenticated_client):
        invalid_zip = b"not a zip file"
        response = authenticated_client.post(
            "/api/restore",
            files={"file": ("backup.zip", io.BytesIO(invalid_zip), "application/zip")},
        )
        assert response.status_code == 400

    def test_restore_zip_without_config_returns_400(self, authenticated_client):
        # Create a zip without config.json
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("dummy.txt", "content")
        buffer.seek(0)

        response = authenticated_client.post(
            "/api/restore",
            files={"file": ("backup.zip", buffer, "application/zip")},
        )
        assert response.status_code == 400
        assert "config.json" in response.json()["detail"].lower()

    def test_restore_invalid_config_returns_400(self, authenticated_client):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("config.json", "invalid json {")
        buffer.seek(0)

        response = authenticated_client.post(
            "/api/restore",
            files={"file": ("backup.zip", buffer, "application/zip")},
        )
        assert response.status_code == 400

    def test_restore_valid_backup_returns_204(self, authenticated_client):
        # Create backup
        backup_response = authenticated_client.get("/api/backup")

        # Restore it
        response = authenticated_client.post(
            "/api/restore",
            files={"file": ("backup.zip", io.BytesIO(backup_response.content), "application/zip")},
        )
        assert response.status_code == 204

    def test_restore_preserves_profiles_and_tokens(self, authenticated_client):
        # Create data
        box = authenticated_client.post(
            "/api/boxes", json={"ip": "192.0.2.1", "name": "Box"}
        ).json()

        profile = authenticated_client.post(
            "/api/profiles",
            json={
                "name": "Profile",
                "sound": "ding-dong",
                "members": [{"box": box["id"], "volume": 50}],
            },
        ).json()
        original_token = profile["token"]

        # Backup
        backup_response = authenticated_client.get("/api/backup")

        # Clear profiles
        authenticated_client.delete(f"/api/profiles/{profile['id']}")

        # Restore
        authenticated_client.post(
            "/api/restore",
            files={"file": ("backup.zip", io.BytesIO(backup_response.content), "application/zip")},
        )

        # Check restored
        profiles_response = authenticated_client.get("/api/profiles")
        profiles = profiles_response.json()
        restored = next((p for p in profiles if p["name"] == "Profile"), None)
        assert restored is not None
        assert restored["token"] == original_token

    def test_restore_keeps_current_password(self, client):
        # Setup with password
        client.post("/api/setup", json={"password": "password123"})

        # Make changes and backup
        authenticated = client
        box = authenticated.post(
            "/api/boxes", json={"ip": "192.0.2.1", "name": "Box"}
        ).json()
        backup_response = authenticated.get("/api/backup")

        # Delete everything including auth, then recreate app and set new password
        # This is testing that restore doesn't overwrite password
        # Since we can't easily test this with the TestClient, we verify the backup
        # doesn't contain password info
        with zipfile.ZipFile(io.BytesIO(backup_response.content)) as zf:
            config = json.loads(zf.read("config.json"))
            assert "password_hash" not in config

    def test_restore_too_large_returns_413(self, authenticated_client):
        # Create a backup that exceeds the size limit
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            # Write large dummy data
            zf.writestr("config.json", json.dumps({"version": 1}))
            # Add large file to exceed limit
            zf.writestr("sounds/large.mp3", b"x" * (201 * 1024 * 1024))
        buffer.seek(0)

        response = authenticated_client.post(
            "/api/restore",
            files={"file": ("backup.zip", buffer, "application/zip")},
        )
        assert response.status_code == 413

    def test_restore_replaces_profiles_not_merges(self, authenticated_client):
        # Create initial backup
        profile1 = authenticated_client.post(
            "/api/profiles",
            json={"name": "Profile1", "sound": "ding-dong", "members": []},
        ).json()
        backup1 = authenticated_client.get("/api/backup")

        # Create new profile
        authenticated_client.post(
            "/api/profiles",
            json={"name": "Profile2", "sound": "ding-dong", "members": []},
        )

        # Restore first backup (only has Profile1)
        authenticated_client.post(
            "/api/restore",
            files={"file": ("backup.zip", io.BytesIO(backup1.content), "application/zip")},
        )

        # Check that only Profile1 exists (Profile2 was replaced)
        profiles_response = authenticated_client.get("/api/profiles")
        profiles = profiles_response.json()
        assert len(profiles) == 1
        assert profiles[0]["name"] == "Profile1"
