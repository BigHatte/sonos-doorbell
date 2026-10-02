"""Keeps a cached map of Sonos players so a ring never waits for discovery."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import soco

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Player:
    name: str
    ip: str
    uid: str  # RINCON_..., also the player id of the S2 websocket API


class PlayerRegistry:
    def __init__(self, static_players: dict[str, str] | None = None):
        self._static = static_players or {}
        self._players: dict[str, Player] = {}
        self._lock = threading.Lock()

    def refresh(self) -> None:
        if self._static:
            devices = [(name, soco.SoCo(ip)) for name, ip in self._static.items()]
        else:
            devices = [(device.player_name, device) for device in soco.discover(timeout=5) or set()]
        found = {}
        for name, device in devices:
            try:
                found[name] = Player(name, device.ip_address, device.uid)
            except Exception as error:
                log.warning("Player %s (%s) nicht erreichbar: %s", name, device.ip_address, error)
        if not found:
            log.warning("Keine Sonos-Player gefunden")
            return
        with self._lock:
            self._players = found
        log.info("Sonos-Player: %s", ", ".join(sorted(found)))

    def set_players(self, players: list[Player]) -> None:
        with self._lock:
            self._players = {p.name: p for p in players}

    def all(self) -> dict[str, Player]:
        with self._lock:
            return dict(self._players)

    def resolve(self, zones: list[str]) -> tuple[list[Player], list[str]]:
        """Returns the players for the given zone names and the names not found."""
        players = self.all()
        if any(zone.casefold() == "all" for zone in zones):
            return list(players.values()), []
        by_name = {name.casefold(): player for name, player in players.items()}
        found, missing = [], []
        for zone in zones:
            player = by_name.get(zone.casefold())
            if player is None:
                missing.append(zone)
            elif player not in found:
                found.append(player)
        return found, missing
