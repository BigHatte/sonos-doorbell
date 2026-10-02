import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SOUNDS = Path(__file__).resolve().parent.parent / "sounds"


@pytest.fixture
def api(tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("advertise_host: docker-host\ndefault_zones: Küche\n", encoding="utf-8")
    monkeypatch.setenv("CONFIG_PATH", str(config))
    monkeypatch.setenv("SOUNDS_DIR", str(SOUNDS))
    import app.main

    module = importlib.reload(app.main)
    return module, TestClient(module.app)


def test_health(api):
    _, client = api
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_sound_file_is_served(api):
    _, client = api
    response = client.get("/sounds/gong.wav")
    assert response.status_code == 200
    assert response.content[:4] == b"RIFF"


def test_ring_passes_parameters(api, monkeypatch):
    module, client = api
    calls = []

    async def fake_ring(zones, sound, volume):
        calls.append((zones, sound, volume))
        return _started()

    monkeypatch.setattr(module.chimer, "ring", fake_ring)

    response = client.get("/ring", params={"zones": "Küche, Bad", "sound": "gong", "volume": 40})

    assert response.status_code == 202
    assert calls == [(["Küche", "Bad"], "gong", 40)]


def test_ring_rejects_invalid_volume(api):
    _, client = api
    assert client.get("/ring", params={"volume": 150}).status_code == 422


def test_ring_without_players_returns_error(api):
    _, client = api
    response = client.get("/ring")
    assert response.status_code == 404
    assert response.json()["status"] == "error"


def _started():
    from app.chime import RingResult

    return RingResult("started", zones=["Küche", "Bad"])


def test_zones_lists_players(api):
    module, client = api
    from app.players import Player

    module.registry.set_players([Player("Küche", "kueche.local", "RINCON_K")])
    assert client.get("/zones").json() == [
        {"name": "Küche", "ip": "kueche.local", "player_id": "RINCON_K", "connected": False}
    ]
