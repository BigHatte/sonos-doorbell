"""Plays the door chime as a Sonos S2 announcement on the boxes of a profile."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import quote

import aiohttp

from . import discovery
from .clip import ClipClient
from .history import History
from .sounds import SoundLibrary
from .store import DEFAULT_SOUND_ID, Box, Profile, Store

log = logging.getLogger(__name__)

TEST_VOLUME = 30

ClientFactory = Callable[[aiohttp.ClientSession, str, str], ClipClient]


@dataclass
class RingResult:
    status: str  # "started", "ignored" or "error"
    reason: str = ""
    boxes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"status": self.status, "reason": self.reason, "boxes": self.boxes}


class Chimer:
    def __init__(
        self,
        store: Store,
        sounds: SoundLibrary,
        history: History,
        base_url: Callable[[], str],
        client_factory: ClientFactory = ClipClient,
        resolve_uid: Callable[[str], str] | None = None,
    ):
        self._store = store
        self._sounds = sounds
        self._history = history
        self._base_url = base_url
        self._client_factory = client_factory
        self._resolve_uid = resolve_uid or (lambda ip: discovery.probe(ip)["uid"])
        self._clients: dict[str, ClipClient] = {}
        self._session: aiohttp.ClientSession | None = None
        self._last_ring: dict[str, float] = {}
        self._tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        for client in self._clients.values():
            await client.close()
        self._clients.clear()
        if self._session:
            await self._session.close()
            self._session = None

    def is_connected(self, box: Box) -> bool:
        client = self._clients.get(box.id)
        return client is not None and client.connected

    async def sync(self) -> None:
        """Drops clients of deleted or changed boxes and resolves missing player ids."""
        boxes = {b.id: b for b in self._store.state.boxes}
        for box_id in [i for i in self._clients if i not in boxes]:
            await self._clients.pop(box_id).close()
        for box in boxes.values():
            await self._ensure_uid(box)

    async def warm_up(self) -> None:
        """Opens the websockets in advance so a ring only has to send one message."""
        await self.sync()
        boxes = [b for b in self._store.state.boxes if b.uid]
        results = await asyncio.gather(*(self._connect(b) for b in boxes), return_exceptions=True)
        for box, result in zip(boxes, results):
            if isinstance(result, Exception):
                log.warning("[%s] Vorab-Verbindung fehlgeschlagen: %s", box.name, result)

    async def ring_profile(
        self, profile: Profile, source: str = "loxone", ignore_cooldown: bool = False, wait: bool = False
    ) -> RingResult:
        requested = time.monotonic()
        sound = self._sounds.get(profile.sound)
        if sound is None or not sound.path.is_file():
            return RingResult("error", "Gong-Datei nicht gefunden")
        targets = []
        for member in profile.members:
            box = self._store.box(member.box)
            if box is not None:
                targets.append((box, member.volume))
        if not targets:
            return RingResult("error", "Profil hat keine Boxen")

        last = self._last_ring.get(profile.id, float("-inf"))
        if not ignore_cooldown and requested - last < profile.cooldown_s:
            return RingResult("ignored", "Sperrzeit")
        self._last_ring[profile.id] = requested
        return await self._start(targets, sound, profile.name, source, requested, wait)

    async def ring_box(self, box: Box, sound_id: str | None = None, volume: int | None = None, wait: bool = False) -> RingResult:
        requested = time.monotonic()
        sound = self._sounds.get(sound_id or DEFAULT_SOUND_ID)
        if sound is None or not sound.path.is_file():
            return RingResult("error", "Gong-Datei nicht gefunden")
        level = TEST_VOLUME if volume is None else max(0, min(100, volume))
        return await self._start([(box, level)], sound, None, "test", requested, wait)

    async def _start(self, targets, sound, profile_name, source, requested, wait) -> RingResult:
        url = f"{self._base_url()}/sounds/{quote(sound.file)}"
        task = asyncio.create_task(self._play_all(targets, url, sound.name, profile_name, source, requested))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        if wait:
            await task
        return RingResult("started", boxes=[box.name for box, _ in targets])

    async def _play_all(self, targets, url, sound_name, profile_name, source, requested) -> None:
        results = await asyncio.gather(*(self._play(b, v, url, requested) for b, v in targets))
        await asyncio.to_thread(self._history.add, source, profile_name, sound_name, list(results))

    async def _play(self, box: Box, volume: int, url: str, requested: float) -> dict:
        try:
            await self._ensure_uid(box)
            if not box.uid:
                raise RuntimeError("Box nicht erreichbar")
            client = await self._client(box)
            await client.play(url, volume)
            ms = round((time.monotonic() - requested) * 1000)
            log.info("[%s] Gong gesendet nach %d ms", box.name, ms)
            return {"box": box.name, "ok": True, "ms": ms, "error": None}
        except Exception as error:
            log.error("[%s] Gong fehlgeschlagen: %s", box.name, error)
            return {"box": box.name, "ok": False, "ms": None, "error": str(error) or type(error).__name__}

    async def _ensure_uid(self, box: Box) -> None:
        if box.uid:
            return
        try:
            box.uid = await asyncio.to_thread(self._resolve_uid, box.ip)
            self._store.save()
        except Exception as error:
            log.warning("[%s] Player-ID nicht ermittelbar: %s", box.name, error)

    async def _client(self, box: Box) -> ClipClient:
        client = self._clients.get(box.id)
        if client is None or client.ip != box.ip or getattr(client, "player_id", box.uid) != box.uid:
            if client is not None:
                await client.close()
            client = self._client_factory(self._session, box.ip, box.uid)
            self._clients[box.id] = client
        return client

    async def _connect(self, box: Box) -> None:
        await (await self._client(box)).connect()
