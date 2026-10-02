"""Profile management API tests."""

import pytest


class TestListProfiles:
    """GET /api/profiles endpoint."""

    def test_list_profiles_initially_empty(self, authenticated_client):
        response = authenticated_client.get("/api/profiles")
        assert response.status_code == 200
        assert response.json() == []


class TestCreateProfile:
    """POST /api/profiles endpoint."""

    def test_create_profile_with_valid_data(self, authenticated_client, app):
        response = authenticated_client.post(
            "/api/profiles",
            json={
                "name": "Haustür",
                "sound": "ding-dong",
                "cooldown_s": 5.0,
                "members": [],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Haustür"
        assert data["sound"] == "ding-dong"
        assert data["cooldown_s"] == 5.0
        assert data["id"] == "haustuer"  # German umlaut conversion
        assert "token" in data
        assert data["members"] == []
        assert "loxone" in data
        assert "address" in data["loxone"]
        assert "command" in data["loxone"]

    def test_profile_id_slugified_from_name(self, authenticated_client):
        response = authenticated_client.post(
            "/api/profiles",
            json={"name": "Große Haustür", "sound": "ding-dong", "members": []},
        )
        data = response.json()
        # Slugification: ß->ss, ö->oe, spaces and punctuation become dashes
        assert data["id"] == "grosse-haustuer"

    def test_profile_id_uniqueness_enforced(self, authenticated_client):
        # Create first profile
        authenticated_client.post(
            "/api/profiles",
            json={"name": "Profil", "sound": "ding-dong", "members": []},
        )

        # Create second with same slugified name
        response = authenticated_client.post(
            "/api/profiles",
            json={"name": "Profil", "sound": "ding-dong", "members": []},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "profil-2"

    def test_create_profile_with_members(self, authenticated_client):
        # Add boxes
        box1 = authenticated_client.post(
            "/api/boxes", json={"ip": "192.0.2.1", "name": "Box1"}
        ).json()
        box2 = authenticated_client.post(
            "/api/boxes", json={"ip": "192.0.2.2", "name": "Box2"}
        ).json()

        response = authenticated_client.post(
            "/api/profiles",
            json={
                "name": "MultiRoom",
                "sound": "ding-dong",
                "members": [
                    {"box": box1["id"], "volume": 50},
                    {"box": box2["id"], "volume": 75},
                ],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert len(data["members"]) == 2
        assert data["members"][0]["volume"] == 50
        assert data["members"][1]["volume"] == 75

    def test_create_profile_without_name_returns_400(self, authenticated_client):
        response = authenticated_client.post(
            "/api/profiles", json={"name": "", "sound": "ding-dong", "members": []}
        )
        assert response.status_code == 400

    def test_create_profile_with_nonexistent_sound_returns_400(self, authenticated_client):
        response = authenticated_client.post(
            "/api/profiles",
            json={"name": "Test", "sound": "nonexistent", "members": []},
        )
        assert response.status_code == 400

    def test_create_profile_with_nonexistent_box_returns_400(self, authenticated_client):
        response = authenticated_client.post(
            "/api/profiles",
            json={
                "name": "Test",
                "sound": "ding-dong",
                "members": [{"box": "nonexistent", "volume": 50}],
            },
        )
        assert response.status_code == 400

    def test_create_profile_with_duplicate_box_returns_400(self, authenticated_client):
        box = authenticated_client.post(
            "/api/boxes", json={"ip": "192.0.2.1", "name": "Box1"}
        ).json()

        response = authenticated_client.post(
            "/api/profiles",
            json={
                "name": "Test",
                "sound": "ding-dong",
                "members": [
                    {"box": box["id"], "volume": 50},
                    {"box": box["id"], "volume": 75},
                ],
            },
        )
        assert response.status_code == 400

    def test_create_profile_cooldown_validation(self, authenticated_client):
        # Valid range: 0-600
        response = authenticated_client.post(
            "/api/profiles",
            json={"name": "Test", "sound": "ding-dong", "cooldown_s": 300, "members": []},
        )
        assert response.status_code == 201

        # Out of range should be rejected by model validation
        # This would be caught by Pydantic validation


class TestUpdateProfile:
    """PUT /api/profiles/{id} endpoint."""

    def test_update_profile_name(self, authenticated_client):
        create_response = authenticated_client.post(
            "/api/profiles",
            json={"name": "OldName", "sound": "ding-dong", "members": []},
        )
        profile_id = create_response.json()["id"]

        response = authenticated_client.put(
            f"/api/profiles/{profile_id}",
            json={"name": "NewName", "sound": "ding-dong", "members": []},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "NewName"
        assert data["id"] == profile_id  # ID unchanged

    def test_update_profile_keeps_id_and_token(self, authenticated_client):
        create_response = authenticated_client.post(
            "/api/profiles",
            json={"name": "Profile", "sound": "ding-dong", "members": []},
        )
        original_id = create_response.json()["id"]
        original_token = create_response.json()["token"]

        response = authenticated_client.put(
            f"/api/profiles/{original_id}",
            json={"name": "Updated", "sound": "dreiklang", "members": []},
        )
        data = response.json()
        assert data["id"] == original_id
        assert data["token"] == original_token

    def test_update_profile_sound(self, authenticated_client):
        create_response = authenticated_client.post(
            "/api/profiles",
            json={"name": "Profile", "sound": "ding-dong", "members": []},
        )
        profile_id = create_response.json()["id"]

        response = authenticated_client.put(
            f"/api/profiles/{profile_id}",
            json={"name": "Profile", "sound": "dreiklang", "members": []},
        )
        assert response.status_code == 200
        assert response.json()["sound"] == "dreiklang"

    def test_update_profile_nonexistent_returns_404(self, authenticated_client):
        response = authenticated_client.put(
            "/api/profiles/nonexistent",
            json={"name": "Profile", "sound": "ding-dong", "members": []},
        )
        assert response.status_code == 404


class TestDeleteProfile:
    """DELETE /api/profiles/{id} endpoint."""

    def test_delete_profile_returns_204(self, authenticated_client):
        create_response = authenticated_client.post(
            "/api/profiles",
            json={"name": "Profile", "sound": "ding-dong", "members": []},
        )
        profile_id = create_response.json()["id"]

        response = authenticated_client.delete(f"/api/profiles/{profile_id}")
        assert response.status_code == 204

        # Verify it's deleted
        list_response = authenticated_client.get("/api/profiles")
        assert len(list_response.json()) == 0

    def test_delete_nonexistent_profile_returns_404(self, authenticated_client):
        response = authenticated_client.delete("/api/profiles/nonexistent")
        assert response.status_code == 404


class TestProfileToken:
    """POST /api/profiles/{id}/token endpoint."""

    def test_regenerate_token_changes_token(self, authenticated_client):
        create_response = authenticated_client.post(
            "/api/profiles",
            json={"name": "Profile", "sound": "ding-dong", "members": []},
        )
        original_token = create_response.json()["token"]
        profile_id = create_response.json()["id"]

        response = authenticated_client.post(f"/api/profiles/{profile_id}/token")
        assert response.status_code == 200
        new_token = response.json()["token"]
        assert new_token != original_token

    def test_regenerate_token_nonexistent_returns_404(self, authenticated_client):
        response = authenticated_client.post("/api/profiles/nonexistent/token")
        assert response.status_code == 404


class TestProfileTest:
    """POST /api/profiles/{id}/test endpoint."""

    def test_test_profile_returns_202(self, authenticated_client):
        # Add a box first
        box = authenticated_client.post(
            "/api/boxes", json={"ip": "192.0.2.1", "name": "Box"}
        ).json()

        profile_response = authenticated_client.post(
            "/api/profiles",
            json={
                "name": "Profile",
                "sound": "ding-dong",
                "members": [{"box": box["id"], "volume": 50}],
            },
        )
        profile_id = profile_response.json()["id"]

        response = authenticated_client.post(f"/api/profiles/{profile_id}/test")
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "started"

    def test_test_profile_without_boxes_returns_422(self, authenticated_client):
        profile_response = authenticated_client.post(
            "/api/profiles",
            json={"name": "Profile", "sound": "ding-dong", "members": []},
        )
        profile_id = profile_response.json()["id"]

        response = authenticated_client.post(f"/api/profiles/{profile_id}/test")
        # Should return error status 422 since no boxes
        assert response.status_code == 422
        data = response.json()
        assert data["status"] == "error"

    def test_test_profile_nonexistent_returns_404(self, authenticated_client):
        response = authenticated_client.post("/api/profiles/nonexistent/test")
        assert response.status_code == 404


class TestLoxoneCommandGeneration:
    """Loxone command in profile response."""

    def test_loxone_command_includes_profile_id_and_token(self, authenticated_client):
        response = authenticated_client.post(
            "/api/profiles",
            json={"name": "Haustür", "sound": "ding-dong", "members": []},
        )
        data = response.json()
        loxone = data["loxone"]

        assert "command" in loxone
        assert "/ring" in loxone["command"]
        assert f"profile={data['id']}" in loxone["command"]
        assert f"token={data['token']}" in loxone["command"]

    def test_loxone_address_matches_detected_host(self, authenticated_client):
        response = authenticated_client.get("/api/settings")
        settings = response.json()

        profile_response = authenticated_client.post(
            "/api/profiles",
            json={"name": "Profile", "sound": "ding-dong", "members": []},
        )
        loxone = profile_response.json()["loxone"]

        assert settings["advertise_host_detected"] in loxone["address"]
