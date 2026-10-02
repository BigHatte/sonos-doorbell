"""Shared fixtures for tests."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from app.main import create_app


class FakeClient:
    """Fake Sonos clip client for testing."""

    def __init__(self, session, ip, uid):
        self.session = session
        self.ip = ip
        self.player_id = uid
        self.connected = False
        self.plays = []
        self.fail_for_uid = set()

    async def connect(self):
        if self.player_id not in self.fail_for_uid:
            self.connected = True

    async def close(self):
        self.connected = False

    async def play(self, url, volume):
        if self.player_id in self.fail_for_uid:
            raise RuntimeError(f"Connection failed for {self.player_id}")
        self.plays.append({"url": url, "volume": volume})


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Temporary data directory for test app."""
    return tmp_path / "data"


@pytest.fixture
def tmp_sounds_dir(tmp_path):
    """Temporary sounds directory."""
    sounds_dir = tmp_path / "sounds"
    sounds_dir.mkdir()
    # Create minimal WAV files for testing built-in sounds
    wav_bytes = bytes([
        0x52, 0x49, 0x46, 0x46,  # "RIFF"
        0x24, 0x00, 0x00, 0x00,  # chunk size = 36
        0x57, 0x41, 0x56, 0x45,  # "WAVE"
        0x66, 0x6d, 0x74, 0x20,  # "fmt "
        0x10, 0x00, 0x00, 0x00,  # subchunk1 size = 16
        0x01, 0x00,  # audio format (PCM)
        0x02, 0x00,  # channels = 2
        0x44, 0xac, 0x00, 0x00,  # sample rate = 44100
        0x10, 0xb1, 0x02, 0x00,  # byte rate
        0x04, 0x00,  # block align
        0x10, 0x00,  # bits per sample = 16
        0x64, 0x61, 0x74, 0x61,  # "data"
        0x00, 0x00, 0x00, 0x00,  # subchunk2 size = 0 (silent)
    ])
    for name in ["ding-dong", "dreiklang", "einzelton", "westminster"]:
        (sounds_dir / f"{name}.wav").write_bytes(wav_bytes)
    return sounds_dir


@pytest.fixture
def fake_probe():
    """Fake probe function that returns box info."""

    def probe(ip):
        # Return consistent data for test IPs
        parts = ip.split(".")
        return {
            "uid": f"RINCON_{parts[-1]}_",
            "name": f"Speaker-{parts[-1]}",
        }

    return probe


@pytest.fixture
def fake_discover():
    """Fake discover function."""

    def discover():
        return [
            {"name": "Speaker-1", "ip": "192.0.2.1", "uid": "RINCON_1_", "model": "S2"},
            {"name": "Speaker-2", "ip": "192.0.2.2", "uid": "RINCON_2_", "model": "S2"},
        ]

    return discover


@pytest.fixture
def fake_detect_ip():
    """Fake LAN IP detection."""

    def detect():
        return "192.0.2.100"

    return detect


@pytest.fixture
def app(tmp_data_dir, tmp_sounds_dir, fake_probe, fake_discover, fake_detect_ip):
    """Create test app with fake components."""
    return create_app(
        data_dir=tmp_data_dir,
        sounds_dir=tmp_sounds_dir,
        client_factory=FakeClient,
        probe=fake_probe,
        discover=fake_discover,
        detect_ip=fake_detect_ip,
        seed_env=False,
    )


@pytest.fixture
def client(app):
    """TestClient with context manager for lifespan support."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def authenticated_client(client):
    """Client already logged in with password 'testpass123'."""
    # Setup password
    response = client.post("/api/setup", json={"password": "testpass123"})
    assert response.status_code == 204
    # Client should now have session cookie
    return client


@pytest.fixture
def fake_client_instances(app):
    """Access to the fake client instances created by the app."""
    return app.state.chimer._clients
