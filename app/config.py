"""Process settings and the one-time environment seed for the first start."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    data_dir: Path
    sounds_dir: Path
    port: int = 5005
    log_level: str = "INFO"
    refresh_s: float = 300.0


def load_settings(data_dir: str | os.PathLike | None = None, sounds_dir: str | os.PathLike | None = None) -> Settings:
    return Settings(
        data_dir=Path(data_dir or os.environ.get("DATA_DIR") or "/data"),
        sounds_dir=Path(sounds_dir or os.environ.get("SOUNDS_DIR") or "/sounds"),
        port=int(os.environ.get("PORT") or 5005),
        log_level=(os.environ.get("LOG_LEVEL") or "INFO").upper(),
        refresh_s=float(os.environ.get("DISCOVERY_REFRESH_S") or 300),
    )


@dataclass
class EnvSeed:
    """Values used to create the initial configuration when no config.json exists."""

    advertise_host: str = ""
    players: dict[str, str] = field(default_factory=dict)
    default_zones: list[str] = field(default_factory=lambda: ["all"])
    default_sound: str = ""
    default_volume: int = 30
    zone_volumes: dict[str, int] = field(default_factory=dict)
    cooldown_s: float = 3.0


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _clamp(value) -> int:
    return max(0, min(100, int(value)))


def _mapping(value: str) -> dict[str, str]:
    """Parses a string like "Küche=40, Bad=20"."""
    pairs = (part.split("=", 1) for part in value.split(",") if "=" in part)
    return {k.strip(): v.strip() for k, v in pairs if k.strip() and v.strip()}


def load_seed() -> EnvSeed:
    zones = [part.strip() for part in _env("DEFAULT_ZONES").split(",") if part.strip()]
    volumes = {}
    for name, value in _mapping(_env("ZONE_VOLUMES")).items():
        try:
            volumes[name] = _clamp(value)
        except ValueError:
            continue
    try:
        volume = _clamp(_env("DEFAULT_VOLUME") or 30)
    except ValueError:
        volume = 30
    try:
        cooldown = max(0.0, min(600.0, float(_env("COOLDOWN_S") or 3)))
    except ValueError:
        cooldown = 3.0
    return EnvSeed(
        advertise_host=_env("ADVERTISE_HOST"),
        players=_mapping(_env("PLAYERS")),
        default_zones=zones or ["all"],
        default_sound=_env("DEFAULT_SOUND"),
        default_volume=volume,
        zone_volumes=volumes,
        cooldown_s=cooldown,
    )
