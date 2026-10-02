"""Client for the local Sonos S2 audio clip API (websocket on port 1443).

An audio clip is mixed over the current playback: the music is ducked while the
clip plays and returns to its previous level afterwards, nothing is paused.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from typing import Any

import aiohttp

log = logging.getLogger(__name__)

# Public key used by the Sonos apps on the local network, no OAuth involved.
API_KEY = "123e4567-e89b-12d3-a456-426655440000"
PROTOCOL = "v1.api.smartspeaker.audio"
APP_ID = "de.loxone.sonos-doorbell"
CLIP_NAME = "Türgong"
HEARTBEAT_S = 30


class ClipError(Exception):
    pass


class ClipClient:
    """One persistent websocket per player, reconnected on demand."""

    def __init__(self, session: aiohttp.ClientSession, ip: str, player_id: str, timeout: float = 4.0, url: str | None = None):
        self.ip = ip
        self.player_id = player_id
        self._session = session
        self._url = url or f"wss://{ip}:1443/websocket/api"
        self._timeout = timeout
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._lock = asyncio.Lock()
        self._cmd_ids = itertools.count(1)

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    async def connect(self) -> None:
        if self.connected:
            return
        try:
            async with asyncio.timeout(self._timeout):
                self._ws = await self._session.ws_connect(
                    self._url,
                    headers={"X-Sonos-Api-Key": API_KEY},
                    protocols=(PROTOCOL,),
                    ssl=False,
                    heartbeat=HEARTBEAT_S,
                )
        except (aiohttp.ClientError, TimeoutError) as error:
            raise ClipError(f"Verbindung zu {self.ip}:1443 fehlgeschlagen: {error}") from error

    async def close(self) -> None:
        if self.connected:
            await self._ws.close()
        self._ws = None

    async def play(self, stream_url: str, volume: int) -> dict[str, Any]:
        command = {"namespace": "audioClip:1", "command": "loadAudioClip", "playerId": self.player_id}
        options = {
            "name": CLIP_NAME,
            "appId": APP_ID,
            "streamUrl": stream_url,
            "clipType": "CUSTOM",
            "priority": "HIGH",
            "volume": volume,
        }
        header, body = await self.send(command, options)
        if not header.get("success", False):
            raise ClipError(f"loadAudioClip abgelehnt: {body}")
        return body

    async def send(self, command: dict[str, Any], options: dict[str, Any] | None = None) -> tuple[dict, dict]:
        async with self._lock:
            for attempt in (1, 2):
                try:
                    await self.connect()
                    return await self._exchange(command, options or {})
                except (ConnectionError, aiohttp.ClientError, ClipError) as error:
                    await self.close()
                    if attempt == 2:
                        raise ClipError(str(error)) from error
                    log.debug("[%s] Verbindung neu aufbauen: %s", self.ip, error)
        raise AssertionError("unreachable")

    async def _exchange(self, command: dict[str, Any], options: dict[str, Any]) -> tuple[dict, dict]:
        cmd_id = str(next(self._cmd_ids))
        await self._ws.send_json([{**command, "cmdId": cmd_id}, options])
        try:
            async with asyncio.timeout(self._timeout):
                while True:
                    message = await self._ws.receive()
                    if message.type != aiohttp.WSMsgType.TEXT:
                        raise ClipError(f"Websocket geschlossen ({message.type.name})")
                    header, body = message.json()
                    # Skip unsolicited events, only take the answer to this command.
                    if header.get("cmdId") in (cmd_id, None) and "response" in header:
                        return header, body
        except TimeoutError as error:
            raise ClipError(f"Keine Antwort von {self.ip}") from error
