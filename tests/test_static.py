"""Static files and public endpoints tests."""

import pytest


class TestIndexHTML:
    """GET / endpoint."""

    def test_root_returns_index_html(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert b"<!DOCTYPE" in response.content or b"<html" in response.content

    def test_root_is_public_no_auth_needed(self, client):
        response = client.get("/")
        assert response.status_code == 200

    def test_root_has_no_cache_header(self, client):
        response = client.get("/")
        cache_control = response.headers.get("cache-control", "").lower()
        assert "no-cache" in cache_control


class TestStaticFiles:
    """GET /static/* endpoints."""

    def test_static_js_returns_200(self, client):
        response = client.get("/static/app.js")
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "").lower()
        assert "javascript" in content_type

    def test_static_css_returns_200(self, client):
        response = client.get("/static/style.css")
        assert response.status_code == 200
        assert "text/css" in response.headers.get("content-type", "")

    def test_static_nonexistent_returns_404(self, client):
        response = client.get("/static/nonexistent.js")
        assert response.status_code == 404


class TestHealth:
    """GET /health endpoint."""

    def test_health_returns_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "boxes" in data

    def test_health_is_public_no_auth_needed(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_box_count_is_accurate(self, client):
        authenticated = client
        authenticated.post("/api/setup", json={"password": "testpass123"})

        # Add boxes
        authenticated.post("/api/boxes", json={"ip": "192.0.2.1", "name": "Box1"})
        authenticated.post("/api/boxes", json={"ip": "192.0.2.2", "name": "Box2"})

        # Check health
        response = client.get("/health")
        data = response.json()
        assert data["boxes"] == 2


class TestSettings:
    """Settings endpoints."""

    def test_get_settings_returns_advertise_host(self, authenticated_client):
        response = authenticated_client.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert "advertise_host" in data
        assert "advertise_host_detected" in data
        assert "port" in data

    def test_get_settings_shows_detected_host(self, authenticated_client):
        response = authenticated_client.get("/api/settings")
        data = response.json()
        # From the fixture, detected should be 192.0.2.100
        assert data["advertise_host_detected"] == "192.0.2.100"

    def test_put_settings_updates_advertise_host(self, authenticated_client):
        response = authenticated_client.put(
            "/api/settings", json={"advertise_host": "example.com"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["advertise_host"] == "example.com"

    def test_put_settings_empty_uses_auto_detect(self, authenticated_client):
        authenticated_client.put(
            "/api/settings", json={"advertise_host": "example.com"}
        )
        response = authenticated_client.put(
            "/api/settings", json={"advertise_host": ""}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["advertise_host"] == ""

    def test_put_settings_invalid_host_returns_400(self, authenticated_client):
        response = authenticated_client.put(
            "/api/settings", json={"advertise_host": "invalid host with spaces"}
        )
        assert response.status_code == 400

    def test_settings_persists_across_requests(self, authenticated_client):
        authenticated_client.put(
            "/api/settings", json={"advertise_host": "myhost.local"}
        )
        response = authenticated_client.get("/api/settings")
        assert response.json()["advertise_host"] == "myhost.local"
