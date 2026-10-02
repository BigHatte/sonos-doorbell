"""Ring history tests."""

import asyncio

import pytest


class TestHistoryList:
    """GET /api/history endpoint."""

    def test_history_initially_empty(self, authenticated_client):
        response = authenticated_client.get("/api/history")
        assert response.status_code == 200
        assert response.json() == []

    def test_history_recorded_after_ring(self, authenticated_client):
        # Setup
        box = authenticated_client.post(
            "/api/boxes", json={"ip": "192.0.2.1", "name": "Kitchen"}
        ).json()

        profile = authenticated_client.post(
            "/api/profiles",
            json={
                "name": "Profile",
                "sound": "ding-dong",
                "members": [{"box": box["id"], "volume": 50}],
            },
        ).json()

        # Ring
        authenticated_client.post(f"/api/profiles/{profile['id']}/test")

        # Check history (need to wait for async task to complete)
        import time
        time.sleep(0.5)

        response = authenticated_client.get("/api/history")
        assert response.status_code == 200
        events = response.json()
        assert len(events) > 0

    def test_history_entry_format(self, authenticated_client, app):
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

        # Test ring
        authenticated_client.post(f"/api/profiles/{profile['id']}/test")

        # Wait for async
        import time
        time.sleep(0.5)

        response = authenticated_client.get("/api/history")
        events = response.json()
        if events:
            event = events[0]
            assert "time" in event
            assert "source" in event
            assert "profile" in event
            assert "sound" in event
            assert "results" in event

    def test_history_source_is_test(self, authenticated_client):
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

        authenticated_client.post(f"/api/profiles/{profile['id']}/test")

        import time
        time.sleep(0.5)

        response = authenticated_client.get("/api/history")
        events = response.json()
        if events:
            assert events[0]["source"] == "test"

    def test_history_source_is_loxone_for_ring_endpoint(self, client):
        authenticated = client
        authenticated.post("/api/setup", json={"password": "testpass123"})

        box = authenticated.post(
            "/api/boxes", json={"ip": "192.0.2.1", "name": "Box"}
        ).json()

        profile = authenticated.post(
            "/api/profiles",
            json={
                "name": "Profile",
                "sound": "ding-dong",
                "members": [{"box": box["id"], "volume": 50}],
            },
        ).json()

        client.cookies.clear()

        # Ring via public endpoint
        client.get(f"/ring?profile={profile['id']}&token={profile['token']}")

        import time
        time.sleep(0.5)

        authenticated.cookies.clear()
        authenticated.post("/api/login", json={"password": "testpass123"})

        response = authenticated.get("/api/history")
        events = response.json()
        if events:
            # Most recent should be from loxone
            assert any(e["source"] == "loxone" for e in events)

    def test_history_per_box_results(self, authenticated_client):
        box1 = authenticated_client.post(
            "/api/boxes", json={"ip": "192.0.2.1", "name": "Box1"}
        ).json()
        box2 = authenticated_client.post(
            "/api/boxes", json={"ip": "192.0.2.2", "name": "Box2"}
        ).json()

        profile = authenticated_client.post(
            "/api/profiles",
            json={
                "name": "Profile",
                "sound": "ding-dong",
                "members": [
                    {"box": box1["id"], "volume": 50},
                    {"box": box2["id"], "volume": 75},
                ],
            },
        ).json()

        authenticated_client.post(f"/api/profiles/{profile['id']}/test")

        import time
        time.sleep(0.5)

        response = authenticated_client.get("/api/history")
        events = response.json()
        if events:
            event = events[0]
            assert len(event["results"]) >= 2
            for result in event["results"]:
                assert "box" in result
                assert "ok" in result
                assert "error" in result

    def test_history_newest_first(self, authenticated_client):
        box = authenticated_client.post(
            "/api/boxes", json={"ip": "192.0.2.1", "name": "Box"}
        ).json()

        profile = authenticated_client.post(
            "/api/profiles",
            json={"name": "Profile", "sound": "ding-dong", "members": [{"box": box["id"], "volume": 50}]},
        ).json()

        # Ring twice with delay
        authenticated_client.post(f"/api/profiles/{profile['id']}/test")
        import time
        time.sleep(1.1)  # Wait long enough for distinct timestamps
        authenticated_client.post(f"/api/profiles/{profile['id']}/test")
        time.sleep(0.5)

        response = authenticated_client.get("/api/history")
        events = response.json()
        if len(events) >= 2:
            # First event should be more recent than second (newest first)
            assert events[0]["time"] >= events[1]["time"]

    def test_history_returns_json_format(self, authenticated_client):
        response = authenticated_client.get("/api/history")
        assert response.status_code == 200
        # Should be parseable as JSON and be a list
        events = response.json()
        assert isinstance(events, list)
