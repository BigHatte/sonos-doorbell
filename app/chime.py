"""Plays the door chime as a Sonos S2 announcement on the selected players."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import aiohttp

from .clip import ClipClient
from .config import Config
from .players import PlayerRegistry

log = logging.getLogger(__name__)

SOUND_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
SOUND_EXTENSIONS = (".mp3", ".wav")


@dataclass
class RingResult:
    status: str  # "started", "ignored" or "error"
    reason: str = ""
    zones: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


ClientFactory = Callable[[aiohttp.ClientSession, str, str], ClipClient]


class Chimer:
    def __init__(self, config: Config, registry: PlayerRegistry, client_factory: ClientFactory = ClipClient):
        self._config = config
        self._registry = registry
        self._client_factory = client_factory
        self._clients: dict[str, ClipClient] = {}
        self._session: aiohttp.ClientSession | None = None
        self._last_ring = float("-inf")
        self._tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        for client in self._clients.values():
            await client.close()
        if self._session:
            await self._session.close()

    async def warm_up(self) -> None:
        """Opens the websockets in advance so a ring only has to send one message."""
        players = list(self._registry.all().values())
        results = await asyncio.gather(*(self._client(p).connect() for p in players), return_exceptions=True)
        for player, result in zip(players, results):
            if isinstance(result, Exception):
                log.warning("[%s] Vorab-Verbindung fehlgeschlagen: %s", player.name, result)

    def is_connected(self, player) -> bool:
        client = self._clients.get(player.uid)
        return client is not None and client.connected

    def find_sound(self, name: str) -> Path | None:
        if not SOUND_NAME.match(name):
            return None
        for extension in SOUND_EXTENSIONS:
            path = self._config.sounds_dir / f"{name}{extension}"
            if path.is_file():
                return path
        return None

    async def ring(
        self,
        zones: list[str] | None = None,
        sound: str | None = None,
        volume: int | None = None,
        wait: bool = False,
    ) -> RingResult:
        requested = time.monotonic()
        zones = zones or self._config.default_zones
        sound = sound or self._config.default_sound

        path = self.find_sound(sound)
        if path is None:
            return RingResult("error", f"Gong-Datei '{sound}' nicht gefunden")

        players, missing = self._registry.resolve(zones)
        if not players:
            return RingResult("error", "Keine passenden Sonos-Player gefunden", missing=missing)

        if requested - self._last_ring < self._config.cooldown_s:
            return RingResult("ignored", f"Cooldown ({self._config.cooldown_s:g} s)")
        self._last_ring = requested

        url = f"http://{self._config.advertise_host}:{self._config.port}/sounds/{quote(path.name)}"
        task = asyncio.create_task(self._play_all(players, url, volume, requested))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        if wait:
            await task
        return RingResult("started", zones=[p.name for p in players], missing=missing)

    async def _play_all(self, players, url: str, volume: int | None, requested: float) -> None:
        await asyncio.gather(*(self._play(p, url, volume, requested) for p in players))

    async def _play(self, player, url: str, volume: int | None, requested: float) -> None:
        try:
            await self._client(player).play(url, self._config.volume_for(player.name, volume))
            log.info("[%s] Gong gesendet nach %.0f ms", player.name, (time.monotonic() - requested) * 1000)
        except Exception as error:
            log.error("[%s] Gong fehlgeschlagen: %s", player.name, error)

    def _client(self, player) -> ClipClient:
        client = self._clients.get(player.uid)
        if client is None or client.ip != player.ip:
            client = self._client_factory(self._session, player.ip, player.uid)
            self._clients[player.uid] = client
        return client
