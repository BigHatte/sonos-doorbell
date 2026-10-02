"""Auth and session tests."""

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.auth import COOKIE_NAME
from app.main import create_app


class TestSessionStatus:
    """GET /api/session endpoint."""

    def test_session_shows_setup_required_initially(self, client):
        response = client.get("/api/session")
        assert response.status_code == 200
        data = response.json()
        assert data["setup_required"] is True
        assert data["logged_in"] is False

    def test_session_shows_logged_in_after_setup(self, authenticated_client):
        response = authenticated_client.get("/api/session")
        assert response.status_code == 200
        data = response.json()
        assert data["setup_required"] is False
        assert data["logged_in"] is True

    def test_session_shows_not_logged_in_without_cookie(self, client):
        # Setup first
        client.post("/api/setup", json={"password": "testpass123"})
        # Clear cookies
        client.cookies.clear()
        response = client.get("/api/session")
        assert response.status_code == 200
        data = response.json()
        assert data["setup_required"] is False
        assert data["logged_in"] is False


class TestSetup:
    """POST /api/setup endpoint."""

    def test_setup_with_valid_password_returns_204_with_cookie(self, client):
        response = client.post("/api/setup", json={"password": "testpass123"})
        assert response.status_code == 204
        assert COOKIE_NAME in client.cookies

    def test_setup_with_short_password_returns_400(self, client):
        response = client.post("/api/setup", json={"password": "short"})
        assert response.status_code == 400
        assert "mindestens" in response.json()["detail"].lower()

    def test_setup_with_exactly_8_chars_password_succeeds(self, client):
        response = client.post("/api/setup", json={"password": "12345678"})
        assert response.status_code == 204

    def test_setup_twice_returns_409(self, authenticated_client):
        response = authenticated_client.post("/api/setup", json={"password": "anotherpass123"})
        assert response.status_code == 409
        assert "bereits" in response.json()["detail"].lower()

    def test_setup_creates_auth_json(self, tmp_path):
        app = create_app(data_dir=tmp_path, sounds_dir=tmp_path, seed_env=False)
        client = TestClient(app)
        client.post("/api/setup", json={"password": "testpass123"})
        auth_file = tmp_path / "auth.json"
        assert auth_file.exists()
        data = json.loads(auth_file.read_text())
        assert "password_hash" in data
        assert "secret" in data


class TestLogin:
    """POST /api/login endpoint."""

    def test_login_with_correct_password_returns_204(self, client):
        client.post("/api/setup", json={"password": "testpass123"})
        client.cookies.clear()
        response = client.post("/api/login", json={"password": "testpass123"})
        assert response.status_code == 204
        assert COOKIE_NAME in client.cookies

    def test_login_with_wrong_password_returns_401(self, client):
        client.post("/api/setup", json={"password": "testpass123"})
        client.cookies.clear()
        response = client.post("/api/login", json={"password": "wrongpass"})
        assert response.status_code == 401
        assert COOKIE_NAME not in client.cookies

    def test_login_before_setup_returns_401(self, client):
        response = client.post("/api/login", json={"password": "anypass"})
        assert response.status_code == 401


class TestLogout:
    """POST /api/logout endpoint."""

    def test_logout_clears_cookie(self, authenticated_client):
        assert COOKIE_NAME in authenticated_client.cookies
        response = authenticated_client.post("/api/logout")
        assert response.status_code == 204
        assert COOKIE_NAME not in authenticated_client.cookies

    def test_after_logout_requests_require_login(self, authenticated_client):
        authenticated_client.post("/api/logout")
        response = authenticated_client.get("/api/boxes")
        assert response.status_code == 401


class TestPasswordChange:
    """PUT /api/password endpoint."""

    def test_change_password_with_correct_current(self, authenticated_client):
        response = authenticated_client.put(
            "/api/password", json={"current": "testpass123", "new": "newpass123"}
        )
        assert response.status_code == 204
        assert COOKIE_NAME in authenticated_client.cookies

    def test_change_password_with_wrong_current_returns_400(self, authenticated_client):
        response = authenticated_client.put(
            "/api/password", json={"current": "wrongpass", "new": "newpass123"}
        )
        assert response.status_code == 400

    def test_change_password_with_short_new_returns_400(self, authenticated_client):
        response = authenticated_client.put(
            "/api/password", json={"current": "testpass123", "new": "short"}
        )
        assert response.status_code == 400

    def test_old_password_no_longer_works_after_change(self, authenticated_client):
        authenticated_client.put(
            "/api/password", json={"current": "testpass123", "new": "newpass123"}
        )
        authenticated_client.cookies.clear()
        response = authenticated_client.post("/api/login", json={"password": "testpass123"})
        assert response.status_code == 401

    def test_new_password_works_after_change(self, authenticated_client):
        authenticated_client.put(
            "/api/password", json={"current": "testpass123", "new": "newpass123"}
        )
        authenticated_client.cookies.clear()
        response = authenticated_client.post("/api/login", json={"password": "newpass123"})
        assert response.status_code == 204

    def test_old_cookie_invalid_after_password_change(self, client):
        client.post("/api/setup", json={"password": "testpass123"})
        old_cookie = client.cookies.get(COOKIE_NAME)

        client.put("/api/password", json={"current": "testpass123", "new": "newpass123"})
        client.cookies.clear()
        client.cookies.set(COOKIE_NAME, old_cookie)

        response = client.get("/api/session")
        assert response.json()["logged_in"] is False


class TestProtectedEndpoints:
    """All /api/* endpoints except auth should return 401 without valid session."""

    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/api/settings"),
            ("GET", "/api/boxes"),
            ("GET", "/api/sounds"),
            ("GET", "/api/profiles"),
            ("GET", "/api/history"),
            ("GET", "/api/backup"),
            ("PUT", "/api/settings"),
            ("POST", "/api/boxes"),
            ("POST", "/api/discover"),
            ("POST", "/api/sounds"),
            ("POST", "/api/profiles"),
        ],
    )
    def test_protected_endpoint_returns_401_without_session(self, client, method, path):
        if method == "GET":
            response = client.get(path)
        elif method == "POST":
            response = client.post(path, json={})
        elif method == "PUT":
            response = client.put(path, json={})
        assert response.status_code == 401, f"{method} {path} should require auth"

    def test_tampered_cookie_rejected(self, client):
        client.post("/api/setup", json={"password": "testpass123"})
        client.cookies.clear()
        client.cookies.set(COOKIE_NAME, "invalid.tamperedvalue123")
        response = client.get("/api/session")
        assert response.json()["logged_in"] is False

    def test_expired_cookie_rejected(self, client):
        client.post("/api/setup", json={"password": "testpass123"})
        client.cookies.clear()
        # Cookie with expired timestamp
        client.cookies.set(COOKIE_NAME, "0.somesignature")
        response = client.get("/api/session")
        assert response.json()["logged_in"] is False


class TestAuthFileDeletion:
    """Deleting auth.json should return to setup_required state."""

    def test_deleting_auth_json_requires_setup_again(self, tmp_path):
        app = create_app(data_dir=tmp_path, sounds_dir=tmp_path, seed_env=False)
        client = TestClient(app)

        # Setup
        client.post("/api/setup", json={"password": "testpass123"})
        response = client.get("/api/session")
        assert response.json()["setup_required"] is False

        # Delete auth.json
        auth_file = tmp_path / "auth.json"
        auth_file.unlink()

        # Should require setup again
        response = client.get("/api/session")
        assert response.json()["setup_required"] is True
