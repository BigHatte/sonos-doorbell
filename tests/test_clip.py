import asyncio
import json

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.clip import API_KEY, PROTOCOL, ClipClient, ClipError


class FakeSonos:
    """Minimal stand-in for the websocket API of a Sonos player."""

    def __init__(self, success=True, send_event_first=False, drop_first_connection=False):
        self.success = success
        self.send_event_first = send_event_first
        self.drop_first_connection = drop_first_connection
        self.requests = []
        self.headers = []
        self.connections = 0

    async def handler(self, request):
        self.connections += 1
        self.headers.append(dict(request.headers))
        ws = web.WebSocketResponse(protocols=(PROTOCOL,))
        await ws.prepare(request)
        if self.drop_first_connection and self.connections == 1:
            await ws.close()
            return ws
        async for message in ws:
            header, body = json.loads(message.data)
            self.requests.append((header, body))
            if self.send_event_first:
                await ws.send_json([{"namespace": "audioClip:1", "type": "audioClipStatus"}, {}])
            await ws.send_json([
                {"namespace": header["namespace"], "response": header["command"],
                 "cmdId": header["cmdId"], "success": self.success},
                {"id": "clip-1", "status": "ACTIVE"} if self.success else {"errorCode": "ERROR_INVALID_PARAMETER"},
            ])
        return ws


def play_against(fake, calls=1):
    async def scenario():
        app = web.Application()
        app.router.add_get("/websocket/api", fake.handler)
        async with TestServer(app) as server, aiohttp.ClientSession() as session:
            client = ClipClient(session, "localhost", "RINCON_K", timeout=2, url=str(server.make_url("/websocket/api")).replace("http", "ws"))
            results = [await client.play("http://host/sounds/gong.wav", 35) for _ in range(calls)]
            await client.close()
            return results

    return asyncio.run(scenario())


def test_sends_load_audio_clip_with_api_key_and_protocol():
    fake = FakeSonos()

    (body,) = play_against(fake)

    assert body["status"] == "ACTIVE"
    header, options = fake.requests[0]
    assert header["namespace"] == "audioClip:1"
    assert header["command"] == "loadAudioClip"
    assert header["playerId"] == "RINCON_K"
    assert options == {
        "name": "Türgong",
        "appId": "de.loxone.sonos-doorbell",
        "streamUrl": "http://host/sounds/gong.wav",
        "clipType": "CUSTOM",
        "priority": "HIGH",
        "volume": 35,
    }
    assert fake.headers[0]["X-Sonos-Api-Key"] == API_KEY
    assert fake.headers[0]["Sec-WebSocket-Protocol"] == PROTOCOL


def test_connection_is_reused_for_further_clips():
    fake = FakeSonos()

    play_against(fake, calls=3)

    assert fake.connections == 1
    assert len({h["cmdId"] for h, _ in fake.requests}) == 3


def test_unrelated_events_are_skipped():
    fake = FakeSonos(send_event_first=True)

    (body,) = play_against(fake)

    assert body["id"] == "clip-1"


def test_reconnects_when_connection_was_dropped():
    fake = FakeSonos(drop_first_connection=True)

    (body,) = play_against(fake)

    assert body["status"] == "ACTIVE"
    assert fake.connections == 2


def test_rejected_clip_raises():
    with pytest.raises(ClipError, match="ERROR_INVALID_PARAMETER"):
        play_against(FakeSonos(success=False))


def test_unreachable_player_raises():
    async def scenario():
        async with aiohttp.ClientSession() as session:
            client = ClipClient(session, "localhost", "RINCON_K", timeout=1, url="ws://localhost:1/websocket/api")
            await client.play("http://host/x.wav", 30)

    with pytest.raises(ClipError):
        asyncio.run(scenario())
