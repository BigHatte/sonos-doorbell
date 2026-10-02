"""Persistent configuration (boxes, profiles, uploaded sounds) as one JSON file."""

from __future__ import annotations

import logging
import os
import re
import secrets
import unicodedata
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field

from .config import EnvSeed

log = logging.getLogger(__name__)

DEFAULT_SOUND_ID = "ding-dong"


class Box(BaseModel):
    id: str
    name: str
    ip: str
    uid: str | None = None


class Member(BaseModel):
    box: str
    volume: int = Field(30, ge=0, le=100)


class Profile(BaseModel):
    id: str
    name: str
    sound: str = DEFAULT_SOUND_ID
    cooldown_s: float = Field(3.0, ge=0, le=600)
    token: str = Field(default_factory=lambda: secrets.token_urlsafe(16))
    members: list[Member] = Field(default_factory=list)


class UploadedSound(BaseModel):
    id: str
    name: str
    file: str
    duration: float | None = None


class State(BaseModel):
    version: int = 1
    advertise_host: str = ""
    boxes: list[Box] = Field(default_factory=list)
    profiles: list[Profile] = Field(default_factory=list)
    sounds: list[UploadedSound] = Field(default_factory=list)


def atomic_write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if isinstance(data, str):
        data = data.encode("utf-8")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def slugify(name: str) -> str:
    text = name.strip().lower()
    for src, dst in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(src, dst)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "profil"


class Store:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "config.json"
        self.fresh = not self.path.exists()
        self.state = State()
        if not self.fresh:
            try:
                self.state = State.model_validate_json(self.path.read_text(encoding="utf-8"))
            except Exception:
                broken = self.path.with_name("config.json.broken")
                log.error("config.json ist ungültig und wird nach %s verschoben", broken.name)
                os.replace(self.path, broken)
                self.fresh = True

    def save(self) -> None:
        atomic_write(self.path, self.state.model_dump_json(indent=2))

    def replace(self, state: State) -> None:
        self.state = state
        self.fresh = False
        self.save()

    def box(self, box_id: str) -> Box | None:
        return next((b for b in self.state.boxes if b.id == box_id), None)

    def profile(self, profile_id: str) -> Profile | None:
        return next((p for p in self.state.profiles if p.id == profile_id), None)

    def new_box_id(self) -> str:
        taken = {b.id for b in self.state.boxes}
        while True:
            candidate = secrets.token_hex(4)
            if candidate not in taken:
                return candidate

    def unique_profile_id(self, name: str) -> str:
        base = slugify(name)
        taken = {p.id for p in self.state.profiles}
        candidate, n = base, 2
        while candidate in taken:
            candidate, n = f"{base}-{n}", n + 1
        return candidate

    def profiles_using_box(self, box_id: str) -> list[str]:
        return sorted(p.name for p in self.state.profiles if any(m.box == box_id for m in p.members))

    def profiles_using_sound(self, sound_id: str) -> list[str]:
        return sorted(p.name for p in self.state.profiles if p.sound == sound_id)


def build_seed_state(seed: EnvSeed, probe: Callable[[str], dict], builtin_ids: set[str]) -> State:
    """Creates the first configuration from environment variables."""
    state = State(advertise_host=seed.advertise_host)
    for name, ip in seed.players.items():
        try:
            uid = probe(ip).get("uid")
        except Exception as error:
            log.warning("Box %s (%s) nicht erreichbar: %s", name, ip, error)
            uid = None
        box_id = secrets.token_hex(4)
        while any(b.id == box_id for b in state.boxes):
            box_id = secrets.token_hex(4)
        state.boxes.append(Box(id=box_id, name=name, ip=ip, uid=uid))
    if state.boxes:
        if any(z.casefold() == "all" for z in seed.default_zones):
            chosen = list(state.boxes)
        else:
            wanted = {z.casefold() for z in seed.default_zones}
            chosen = [b for b in state.boxes if b.name.casefold() in wanted]
        volumes = {k.casefold(): v for k, v in seed.zone_volumes.items()}
        sound = seed.default_sound if seed.default_sound in builtin_ids else DEFAULT_SOUND_ID
        state.profiles.append(
            Profile(
                id="standard",
                name="Standard",
                sound=sound,
                cooldown_s=seed.cooldown_s,
                members=[Member(box=b.id, volume=volumes.get(b.name.casefold(), seed.default_volume)) for b in chosen],
            )
        )
    return state
