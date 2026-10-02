"""Blocking Sonos helpers (multicast discovery, probing by IP, LAN address)."""

from __future__ import annotations

import logging
import socket

import soco

log = logging.getLogger(__name__)

soco.config.REQUEST_TIMEOUT = 5


def discover() -> list[dict]:
    """Finds speakers via multicast; returns name, ip, uid and model of each."""
    found = []
    for device in soco.discover(timeout=5) or set():
        try:
            try:
                model = device.get_speaker_info().get("model_name", "")
            except Exception:
                model = ""
            found.append({"name": device.player_name, "ip": device.ip_address, "uid": device.uid, "model": model})
        except Exception as error:
            log.warning("Box %s nicht lesbar: %s", device.ip_address, error)
    return sorted(found, key=lambda d: d["name"].casefold())


def probe(ip: str) -> dict:
    """Reads uid and name of the speaker at the given address."""
    device = soco.SoCo(ip)
    return {"uid": device.uid, "name": device.player_name}


def detect_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
