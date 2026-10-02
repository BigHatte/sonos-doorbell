"""HTTP entry point called by the Loxone Miniserver via a virtual output."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .chime import Chimer
from .config import load_config
from .players import PlayerRegistry

config = load_config()
logging.basicConfig(
    level=config.log_level,
    format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sonos_doorbell")

registry = PlayerRegistry(config.players)
chimer = Chimer(config, registry)


async def refresh_players() -> None:
    try:
        await asyncio.to_thread(registry.refresh)
    except Exception:
        log.exception("Player-Suche fehlgeschlagen")
    await chimer.warm_up()


async def refresh_loop() -> None:
    while True:
        await asyncio.sleep(config.discovery_refresh_s)
        await refresh_players()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await chimer.start()
    await refresh_players()
    refresher = asyncio.create_task(refresh_loop())
    yield
    refresher.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await refresher
    await chimer.close()


app = FastAPI(title="Sonos-Türgong", lifespan=lifespan)
app.mount("/sounds", StaticFiles(directory=config.sounds_dir), name="sounds")

STATUS_CODES = {"started": 202, "ignored": 200, "error": 404}


@app.get("/ring")
async def ring(
    zones: str | None = Query(None, description="Kommagetrennte Raumnamen oder 'all'"),
    sound: str | None = Query(None, description="Dateiname ohne Endung aus dem Sounds-Ordner"),
    volume: int | None = Query(None, ge=0, le=100),
):
    zone_list = [z.strip() for z in zones.split(",") if z.strip()] if zones else None
    result = await chimer.ring(zone_list, sound, volume)
    if result.status != "started":
        log.info("Klingeln %s: %s", result.status, result.reason)
    elif result.missing:
        log.warning("Unbekannte Zonen ignoriert: %s", ", ".join(result.missing))
    return JSONResponse(result.__dict__, status_code=STATUS_CODES[result.status])


@app.get("/zones")
async def zones():
    return [
        {"name": p.name, "ip": p.ip, "player_id": p.uid, "connected": chimer.is_connected(p)}
        for _, p in sorted(registry.all().items())
    ]


@app.get("/health")
async def health():
    return {"status": "ok", "players": len(registry.all())}
