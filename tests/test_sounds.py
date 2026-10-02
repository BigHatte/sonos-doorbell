"""Sound management API tests (simplified for environments without ffmpeg)."""

import io
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest


class TestListSounds:
    """GET /api/sounds endpoint."""

    def test_list_sounds_includes_builtin(self, authenticated_client):
        response = authenticated_client.get("/api/sounds")
        assert response.status_code == 200
        sounds = response.json()

        builtin_ids = {"ding-dong", "dreiklang", "einzelton", "westminster"}
        found_ids = {s["id"] for s in sounds if s["builtin"]}
        assert builtin_ids.issubset(found_ids)

    def test_builtin_sounds_listed_first(self, authenticated_client):
        response = authenticated_client.get("/api/sounds")
        sounds = response.json()
        # First sounds should be builtins
        if sounds:
            for sound in sounds[:4]:
                assert sound["builtin"] is True

    def test_sound_has_required_fields(self, authenticated_client):
        response = authenticated_client.get("/api/sounds")
        sounds = response.json()
        if sounds:
            sound = sounds[0]
            assert "id" in sound
            assert "name" in sound
            assert "builtin" in sound
            assert "url" in sound
            assert "duration" in sound
            assert "profiles" in sound

    def test_sound_url_format(self, authenticated_client):
        response = authenticated_client.get("/api/sounds")
        sounds = response.json()
        builtin = next((s for s in sounds if s["builtin"]), None)
        if builtin:
            assert builtin["url"].startswith("/sounds/")
            assert builtin["url"].endswith(".wav")


class TestDeleteBuiltin:
    """Deleting built-in sounds should return 400."""

    def test_delete_builtin_returns_400(self, authenticated_client):
        response = authenticated_client.delete("/api/sounds/ding-dong")
        assert response.status_code == 400
        assert "fest" in response.json()["detail"].lower() or "built" in response.json()["detail"].lower()

    def test_rename_builtin_returns_400(self, authenticated_client):
        response = authenticated_client.put(
            "/api/sounds/ding-dong", json={"name": "NewName"}
        )
        assert response.status_code == 400


class TestServeSound:
    """GET /sounds/{filename} endpoint."""

    def test_serve_builtin_sound_returns_200(self, client):
        response = client.get("/sounds/ding-dong.wav")
        assert response.status_code == 200
        assert "audio" in response.headers.get("content-type", "").lower()

    def test_serve_sound_public_no_auth_needed(self, client):
        # Should work without authentication
        response = client.get("/sounds/ding-dong.wav")
        assert response.status_code == 200

    def test_serve_nonexistent_sound_returns_404(self, client):
        response = client.get("/sounds/nonexistent.wav")
        assert response.status_code == 404

    def test_path_traversal_attempt_returns_400_or_404(self, client):
        response = client.get("/sounds/../../../etc/passwd")
        assert response.status_code in [400, 404]

    def test_invalid_filename_pattern_returns_404(self, client):
        response = client.get("/sounds/file with spaces.wav")
        assert response.status_code == 404

    def test_invalid_extension_returns_404(self, client):
        response = client.get("/sounds/sound.txt")
        assert response.status_code == 404


class TestUploadSound:
    """POST /api/sounds endpoint."""

    def test_upload_sound_without_ffmpeg_returns_503(self, authenticated_client):
        with patch("app.sounds.shutil.which") as mock_which:
            mock_which.return_value = None
            data = {"file": ("test.wav", io.BytesIO(b"fake audio"), "audio/wav")}
            response = authenticated_client.post(
                "/api/sounds",
                data={"name": "Test Sound"},
                files={"file": data["file"]},
            )
            assert response.status_code == 503
            assert "ffmpeg" in response.json()["detail"].lower()

    def test_upload_sound_without_name_returns_400(self, authenticated_client):
        data = {"file": ("test.wav", io.BytesIO(b"fake audio"), "audio/wav")}
        response = authenticated_client.post(
            "/api/sounds",
            data={"name": ""},
            files={"file": data["file"]},
        )
        assert response.status_code == 400

    def test_upload_empty_file_returns_400(self, authenticated_client):
        data = {"file": ("test.wav", io.BytesIO(b""), "audio/wav")}
        response = authenticated_client.post(
            "/api/sounds",
            data={"name": "Test Sound"},
            files={"file": data["file"]},
        )
        assert response.status_code == 400

    def test_upload_file_exceeding_20mb_returns_413(self, authenticated_client):
        # Create a file larger than 20MB
        large_data = io.BytesIO(b"x" * (21 * 1024 * 1024))
        data = {"file": ("test.wav", large_data, "audio/wav")}
        response = authenticated_client.post(
            "/api/sounds",
            data={"name": "Test Sound"},
            files={"file": data["file"]},
        )
        assert response.status_code == 413


class TestRenameSound:
    """PUT /api/sounds/{id} endpoint."""

    def test_rename_sound_empty_name_returns_400(self, authenticated_client):
        response = authenticated_client.put(
            "/api/sounds/ding-dong", json={"name": ""}
        )
        assert response.status_code == 400

    def test_rename_nonexistent_sound_returns_404(self, authenticated_client):
        response = authenticated_client.put(
            "/api/sounds/nonexistent", json={"name": "New Name"}
        )
        assert response.status_code == 404


class TestDeleteSound:
    """DELETE /api/sounds/{id} endpoint."""

    def test_delete_nonexistent_sound_returns_404(self, authenticated_client):
        response = authenticated_client.delete("/api/sounds/nonexistent")
        assert response.status_code == 404

    def test_delete_builtin_returns_400(self, authenticated_client):
        response = authenticated_client.delete("/api/sounds/ding-dong")
        assert response.status_code == 400
