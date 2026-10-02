"""HTTP entry point: web interface API for people and /ring for the Loxone Miniserver."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import ipaddress
import logging
import re
import secrets
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import backup, discovery
from .auth import COOKIE_NAME, MIN_PASSWORD, SESSION_SECONDS, Auth
from .chime import Chimer
from .config import load_seed, load_settings
from .history import History
from .sounds import SoundError, SoundLibrary
from .store import Box, Member, Profile, Store, build_seed_state

log = logging.getLogger("sonos_doorbell")

STATIC_DIR = Path(__file__).parent / "static"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
HOST_PATTERN = re.compile(r"^[A-Za-z0-9.:_-]{1,253}$")


class PasswordIn(BaseModel):
    password: str


class PasswordChangeIn(BaseModel):
    current: str
    new: str


class SettingsIn(BaseModel):
    advertise_host: str = ""


class BoxIn(BaseModel):
    ip: str
    name: str = ""


class BoxTestIn(BaseModel):
    sound: str | None = None
    volume: int | None = Field(None, ge=0, le=100)


class NameIn(BaseModel):
    name: str


class ProfileIn(BaseModel):
    name: str
    sound: str
    cooldown_s: float = Field(3.0, ge=0, le=600)
    members: list[Member] = Field(default_factory=list)


def create_app(
    data_dir=None,
    sounds_dir=None,
    client_factory=None,
    probe: Callable[[str], dict] | None = None,
    discover: Callable[[], list[dict]] | None = None,
    detect_ip: Callable[[], str] | None = None,
    seed_env: bool = True,
) -> FastAPI:
    """Builds the application. Tests can inject a fake clip client factory and network helpers."""
    settings = load_settings(data_dir, sounds_dir)
    probe = probe or discovery.probe
    discover = discover or discovery.discover
    detect_ip = detect_ip or discovery.detect_lan_ip

    store = Store(settings.data_dir)
    auth = Auth(settings.data_dir)
    history = History(settings.data_dir)
    sounds = SoundLibrary(store, settings.sounds_dir, settings.data_dir / "sounds")

    def host() -> str:
        return store.state.advertise_host or detect_ip()

    def base_url() -> str:
        return f"http://{host()}:{settings.port}"

    chime_args = {"client_factory": client_factory} if client_factory else {}
    chimer = Chimer(store, sounds, history, base_url, **chime_args)
    background: set[asyncio.Task] = set()

    def in_background(coro) -> None:
        task = asyncio.create_task(coro)
        background.add(task)
        task.add_done_callback(background.discard)

    async def refresh_loop() -> None:
        while True:
            try:
                await chimer.warm_up()
            except Exception:
                log.exception("Aktualisierung der Verbindungen fehlgeschlagen")
            await asyncio.sleep(settings.refresh_s)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if store.fresh and seed_env:
            state = await asyncio.to_thread(build_seed_state, load_seed(), probe, sounds.builtin_ids())
            store.replace(state)
            log.info("Erste Konfiguration aus Umgebungsvariablen angelegt")
        await chimer.start()
        refresher = asyncio.create_task(refresh_loop())
        yield
        refresher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await refresher
        await chimer.close()

    app = FastAPI(title="Sonos-Türgong", lifespan=lifespan)
    app.state.store = store
    app.state.chimer = chimer
    app.state.auth = auth
    app.state.history = history
    app.state.sounds = sounds
    app.state.settings = settings

    @app.middleware("http")
    async def revalidate_static(request: Request, call_next):
        # Browsers must not keep an old UI after an update.
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_input(_: Request, error: RequestValidationError):
        fields = ", ".join(str(e["loc"][-1]) for e in error.errors() if e.get("loc"))
        return JSONResponse({"detail": f"Ungültige Eingabe: {fields}" if fields else "Ungültige Eingabe"}, status_code=422)

    def require_session(request: Request) -> None:
        if not auth.valid_cookie(request.cookies.get(COOKIE_NAME)):
            raise HTTPException(401, "Nicht angemeldet")

    def set_cookie(response: Response) -> None:
        response.set_cookie(
            COOKIE_NAME, auth.make_cookie(), max_age=SESSION_SECONDS, httponly=True, samesite="lax", path="/"
        )

    def no_content(login: bool = False) -> Response:
        response = Response(status_code=204)
        if login:
            set_cookie(response)
        return response

    # ---- views -------------------------------------------------------------

    def box_view(box: Box) -> dict:
        return {
            "id": box.id,
            "name": box.name,
            "ip": box.ip,
            "uid": box.uid,
            "connected": chimer.is_connected(box),
            "profiles": store.profiles_using_box(box.id),
        }

    def sound_view(sound) -> dict:
        return {
            "id": sound.id,
            "name": sound.name,
            "builtin": sound.builtin,
            "url": f"/sounds/{sound.file}",
            "duration": sound.duration,
            "profiles": store.profiles_using_sound(sound.id),
        }

    def profile_view(profile: Profile) -> dict:
        data = profile.model_dump()
        data["loxone"] = {
            "address": base_url(),
            "command": f"/ring?profile={profile.id}&token={profile.token}",
        }
        return data

    def settings_view() -> dict:
        return {"advertise_host": store.state.advertise_host, "advertise_host_detected": detect_ip(), "port": settings.port}

    def get_profile(profile_id: str) -> Profile:
        profile = store.profile(profile_id)
        if profile is None:
            raise HTTPException(404, "Profil nicht gefunden")
        return profile

    def get_box(box_id: str) -> Box:
        box = store.box(box_id)
        if box is None:
            raise HTTPException(404, "Box nicht gefunden")
        return box

    def clean_ip(value: str) -> str:
        try:
            return str(ipaddress.ip_address(value.strip()))
        except ValueError:
            raise HTTPException(400, "Ungültige IP-Adresse") from None

    async def probe_box(ip: str) -> dict:
        try:
            return await asyncio.to_thread(probe, ip)
        except Exception:
            raise HTTPException(400, f"Box unter {ip} nicht erreichbar") from None

    def result_response(result) -> JSONResponse:
        codes = {"started": 202, "ignored": 200, "error": 422}
        return JSONResponse(result.as_dict(), status_code=codes[result.status])

    # ---- auth --------------------------------------------------------------

    @app.get("/api/session")
    async def session(request: Request):
        return {
            "setup_required": not auth.configured,
            "logged_in": auth.valid_cookie(request.cookies.get(COOKIE_NAME)),
        }

    @app.post("/api/setup")
    async def setup(body: PasswordIn):
        if auth.configured:
            raise HTTPException(409, "Es ist bereits ein Passwort festgelegt")
        if len(body.password) < MIN_PASSWORD:
            raise HTTPException(400, f"Das Passwort muss mindestens {MIN_PASSWORD} Zeichen lang sein")
        await asyncio.to_thread(auth.set_password, body.password)
        return no_content(login=True)

    @app.post("/api/login")
    async def login(body: PasswordIn):
        if not await asyncio.to_thread(auth.verify, body.password):
            await asyncio.sleep(1)
            raise HTTPException(401, "Falsches Passwort")
        return no_content(login=True)

    @app.post("/api/logout")
    async def logout():
        response = Response(status_code=204)
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    api = Depends(require_session)

    @app.put("/api/password", dependencies=[api])
    async def change_password(body: PasswordChangeIn):
        if not await asyncio.to_thread(auth.verify, body.current):
            raise HTTPException(400, "Das aktuelle Passwort ist falsch")
        if len(body.new) < MIN_PASSWORD:
            raise HTTPException(400, f"Das neue Passwort muss mindestens {MIN_PASSWORD} Zeichen lang sein")
        await asyncio.to_thread(auth.set_password, body.new)
        return no_content(login=True)

    # ---- settings ----------------------------------------------------------

    @app.get("/api/settings", dependencies=[api])
    async def get_settings():
        return settings_view()

    @app.put("/api/settings", dependencies=[api])
    async def put_settings(body: SettingsIn):
        value = body.advertise_host.strip()
        if value and not HOST_PATTERN.match(value):
            raise HTTPException(400, "Ungültige Adresse")
        store.state.advertise_host = value
        store.save()
        return settings_view()

    # ---- boxes -------------------------------------------------------------

    @app.get("/api/boxes", dependencies=[api])
    async def list_boxes():
        return [box_view(b) for b in sorted(store.state.boxes, key=lambda b: b.name.casefold())]

    @app.post("/api/boxes", dependencies=[api], status_code=201)
    async def add_box(body: BoxIn):
        ip = clean_ip(body.ip)
        if any(b.ip == ip for b in store.state.boxes):
            raise HTTPException(409, "Diese Box ist bereits angelegt")
        info = await probe_box(ip)
        name = body.name.strip() or info.get("name") or ip
        box = Box(id=store.new_box_id(), name=name, ip=ip, uid=info.get("uid"))
        store.state.boxes.append(box)
        store.save()
        in_background(chimer.warm_up())
        return box_view(box)

    @app.put("/api/boxes/{box_id}", dependencies=[api])
    async def update_box(box_id: str, body: BoxIn):
        box = get_box(box_id)
        ip = clean_ip(body.ip)
        if any(b.ip == ip and b.id != box.id for b in store.state.boxes):
            raise HTTPException(409, "Diese IP ist bereits einer anderen Box zugeordnet")
        if ip != box.ip:
            info = await probe_box(ip)
            box.ip, box.uid = ip, info.get("uid")
        box.name = body.name.strip() or box.name
        store.save()
        in_background(chimer.warm_up())
        return box_view(box)

    @app.delete("/api/boxes/{box_id}", dependencies=[api])
    async def delete_box(box_id: str):
        box = get_box(box_id)
        store.state.boxes.remove(box)
        for profile in store.state.profiles:
            profile.members = [m for m in profile.members if m.box != box_id]
        store.save()
        await chimer.sync()
        return no_content()

    @app.post("/api/discover", dependencies=[api])
    async def discover_boxes():
        try:
            found = await asyncio.to_thread(discover)
        except Exception:
            log.exception("Box-Suche fehlgeschlagen")
            found = []
        known_ips = {b.ip for b in store.state.boxes}
        known_uids = {b.uid for b in store.state.boxes if b.uid}
        return [{**d, "added": d["ip"] in known_ips or d["uid"] in known_uids} for d in found]

    @app.post("/api/boxes/{box_id}/test", dependencies=[api])
    async def test_box(box_id: str, body: BoxTestIn | None = None):
        box = get_box(box_id)
        body = body or BoxTestIn()
        if body.sound and not sounds.exists(body.sound):
            raise HTTPException(400, "Gong nicht gefunden")
        result = await chimer.ring_box(box, body.sound, body.volume)
        return JSONResponse(result.as_dict(), status_code=202 if result.status == "started" else 422)

    # ---- sounds ------------------------------------------------------------

    @app.get("/api/sounds", dependencies=[api])
    async def list_sounds():
        return [sound_view(s) for s in sounds.all()]

    @app.post("/api/sounds", dependencies=[api], status_code=201)
    async def upload_sound(file: UploadFile = File(...), name: str = Form("")):
        name = name.strip()
        if not name:
            raise HTTPException(400, "Bitte einen Namen angeben")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "upload"
            size = 0
            with open(source, "wb") as out:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, "Die Datei ist größer als 20 MB")
                    out.write(chunk)
            if size == 0:
                raise HTTPException(400, "Die Datei ist leer")
            try:
                item = await sounds.add_upload(source, name)
            except SoundError as error:
                raise HTTPException(error.status, error.detail) from None
        return sound_view(sounds.get(item.id))

    def get_upload(sound_id: str):
        item = next((s for s in store.state.sounds if s.id == sound_id), None)
        if item is None:
            if sound_id in sounds.builtin_ids():
                raise HTTPException(400, "Fest eingebaute Gongs können nicht geändert werden")
            raise HTTPException(404, "Gong nicht gefunden")
        return item

    @app.put("/api/sounds/{sound_id}", dependencies=[api])
    async def rename_sound(sound_id: str, body: NameIn):
        item = get_upload(sound_id)
        name = body.name.strip()
        if not name:
            raise HTTPException(400, "Bitte einen Namen angeben")
        item.name = name
        store.save()
        return sound_view(sounds.get(sound_id))

    @app.delete("/api/sounds/{sound_id}", dependencies=[api])
    async def delete_sound(sound_id: str):
        item = get_upload(sound_id)
        used = store.profiles_using_sound(sound_id)
        if used:
            raise HTTPException(409, f"Gong wird noch verwendet von: {', '.join(used)}")
        sounds.remove(item)
        return no_content()

    @app.api_route("/sounds/{filename}", methods=["GET", "HEAD"])
    async def serve_sound(filename: str):
        path = sounds.file_path(filename)
        if path is None:
            raise HTTPException(404, "Datei nicht gefunden")
        return FileResponse(path, media_type="audio/mpeg" if path.suffix == ".mp3" else "audio/wav")

    # ---- profiles ----------------------------------------------------------

    def validate_profile(body: ProfileIn) -> tuple[str, list[Member]]:
        name = body.name.strip()
        if not name:
            raise HTTPException(400, "Bitte einen Namen angeben")
        if not sounds.get(body.sound):
            raise HTTPException(400, "Gong nicht gefunden")
        seen = set()
        for member in body.members:
            if store.box(member.box) is None:
                raise HTTPException(400, "Box nicht gefunden")
            if member.box in seen:
                raise HTTPException(400, "Eine Box ist mehrfach angegeben")
            seen.add(member.box)
        return name, body.members

    @app.get("/api/profiles", dependencies=[api])
    async def list_profiles():
        return [profile_view(p) for p in store.state.profiles]

    @app.post("/api/profiles", dependencies=[api], status_code=201)
    async def create_profile(body: ProfileIn):
        name, members = validate_profile(body)
        profile = Profile(
            id=store.unique_profile_id(name), name=name, sound=body.sound, cooldown_s=body.cooldown_s, members=members
        )
        store.state.profiles.append(profile)
        store.save()
        return profile_view(profile)

    @app.put("/api/profiles/{profile_id}", dependencies=[api])
    async def update_profile(profile_id: str, body: ProfileIn):
        profile = get_profile(profile_id)
        profile.name, profile.members = validate_profile(body)
        profile.sound, profile.cooldown_s = body.sound, body.cooldown_s
        store.save()
        return profile_view(profile)

    @app.delete("/api/profiles/{profile_id}", dependencies=[api])
    async def delete_profile(profile_id: str):
        store.state.profiles.remove(get_profile(profile_id))
        store.save()
        return no_content()

    @app.post("/api/profiles/{profile_id}/token", dependencies=[api])
    async def new_token(profile_id: str):
        profile = get_profile(profile_id)
        profile.token = secrets.token_urlsafe(16)
        store.save()
        return profile_view(profile)

    @app.post("/api/profiles/{profile_id}/test", dependencies=[api])
    async def test_profile(profile_id: str):
        result = await chimer.ring_profile(get_profile(profile_id), source="test", ignore_cooldown=True)
        return JSONResponse(result.as_dict(), status_code=202 if result.status == "started" else 422)

    # ---- history, backup ---------------------------------------------------

    @app.get("/api/history", dependencies=[api])
    async def get_history():
        return await asyncio.to_thread(history.list)

    @app.get("/api/backup", dependencies=[api])
    async def download_backup():
        data = await asyncio.to_thread(backup.make_backup, store.state, sounds.upload_dir)
        filename = f"sonos-doorbell-backup-{datetime.now():%Y%m%d-%H%M}.zip"
        return Response(
            data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    @app.post("/api/restore", dependencies=[api])
    async def restore(file: UploadFile = File(...)):
        data = await file.read(backup.MAX_RESTORE_BYTES + 1)
        if len(data) > backup.MAX_RESTORE_BYTES:
            raise HTTPException(413, "Das Backup ist zu groß")
        try:
            state, files = await asyncio.to_thread(backup.read_backup, data)
        except backup.BackupError as error:
            raise HTTPException(400, str(error)) from None
        await asyncio.to_thread(backup.apply_files, files, sounds.upload_dir)
        store.replace(state)
        await chimer.sync()
        in_background(chimer.warm_up())
        return no_content()

    # ---- public ------------------------------------------------------------

    @app.get("/ring")
    async def ring(profile: str | None = None, token: str | None = None):
        found = store.profile(profile) if profile else None
        if found is None or not token or not hmac.compare_digest(token.encode(), found.token.encode()):
            return JSONResponse({"status": "error", "reason": "Profil oder Token ungültig"}, status_code=403)
        result = await chimer.ring_profile(found, source="loxone")
        if result.status != "started":
            log.info("Klingeln %s: %s", result.status, result.reason)
        return result_response(result)

    @app.get("/health")
    async def health():
        return {"status": "ok", "boxes": len(store.state.boxes)}

    @app.get("/", include_in_schema=False)
    async def index():
        page = STATIC_DIR / "index.html"
        if not page.is_file():
            raise HTTPException(404, "Oberfläche nicht gefunden")
        return FileResponse(page, headers={"Cache-Control": "no-cache"})

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


logging.basicConfig(
    level=load_settings().log_level,
    format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
app = create_app()
