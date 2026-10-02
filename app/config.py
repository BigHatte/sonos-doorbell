"""Loads the service configuration from a YAML file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = "/config/config.yaml"


@dataclass
class Config:
    advertise_host: str
    port: int = 5005
    sounds_dir: Path = Path("/sounds")
    default_zones: list[str] = field(default_factory=lambda: ["all"])
    default_sound: str = "gong"
    default_volume: int = 30
    zone_volumes: dict[str, int] = field(default_factory=dict)
    cooldown_s: float = 3.0
    players: dict[str, str] = field(default_factory=dict)
    discovery_refresh_s: float = 300.0
    log_level: str = "INFO"

    def volume_for(self, zone: str, override: int | None) -> int:
        if override is not None:
            return _clamp_volume(override)
        for name, volume in self.zone_volumes.items():
            if name.casefold() == zone.casefold():
                return _clamp_volume(volume)
        return _clamp_volume(self.default_volume)


def _clamp_volume(value: int) -> int:
    return max(0, min(100, int(value)))


def _as_list(value) -> list[str]:
    if value is None:
        return ["all"]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(part).strip() for part in value if str(part).strip()]


def _as_mapping(value) -> dict[str, str]:
    """Accepts a YAML mapping or a string like "Küche=40, Bad=20"."""
    if not value:
        return {}
    if isinstance(value, dict):
        return {str(k).strip(): str(v).strip() for k, v in value.items()}
    pairs = (part.split("=", 1) for part in str(value).split(",") if "=" in part)
    return {k.strip(): v.strip() for k, v in pairs if k.strip() and v.strip()}


def _setting(raw: dict, key: str, default=None):
    """Environment variable (upper case key) wins over the YAML file."""
    value = os.environ.get(key.upper())
    if value is not None and value.strip() != "":
        return value
    return raw.get(key, default)


def load_config(path: str | os.PathLike | None = None) -> Config:
    path = Path(path or os.environ.get("CONFIG_PATH", DEFAULT_CONFIG_PATH))
    raw = {}
    if path.is_file():
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}

    advertise_host = _setting(raw, "advertise_host")
    if not advertise_host:
        raise ValueError(
            "advertise_host fehlt: IP des Docker-Hosts, über die die Sonos-Player "
            "die Gong-Datei abrufen (config.yaml oder Umgebungsvariable ADVERTISE_HOST)."
        )

    return Config(
        advertise_host=str(advertise_host),
        port=int(_setting(raw, "port", 5005)),
        sounds_dir=Path(_setting(raw, "sounds_dir", "/sounds")),
        default_zones=_as_list(_setting(raw, "default_zones")),
        default_sound=str(_setting(raw, "default_sound", "gong")),
        default_volume=int(_setting(raw, "default_volume", 30)),
        zone_volumes={k: int(v) for k, v in _as_mapping(_setting(raw, "zone_volumes")).items()},
        cooldown_s=float(_setting(raw, "cooldown_s", 3.0)),
        players=_as_mapping(_setting(raw, "players")),
        discovery_refresh_s=float(_setting(raw, "discovery_refresh_s", 300.0)),
        log_level=str(_setting(raw, "log_level", "INFO")).upper(),
    )
