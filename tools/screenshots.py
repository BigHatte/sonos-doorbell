"""Creates the screenshots for the documentation from a demo configuration.

Starts the app in-process with fake Sonos boxes and demo data, then drives a
headless Chromium/Edge through the DevTools protocol.

Usage: python tools/screenshots.py [--out docs/screenshots]
Set BROWSER_PATH to use a specific browser executable.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import wave
from datetime import datetime, timedelta
from pathlib import Path

import aiohttp
import uvicorn

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.auth import COOKIE_NAME  # noqa: E402
from app.main import create_app  # noqa: E402
from app.store import Box, Member, Profile, UploadedSound  # noqa: E402

DESKTOP_WIDTH = 1280
MOBILE_WIDTH = 390

BOXES = [
    ("Wohnzimmer", "192.0.2.21"),
    ("Küche", "192.0.2.22"),
    ("Flur", "192.0.2.23"),
    ("Büro", "192.0.2.24"),
]


# ---------------------------------------------------------------- demo setup


class DemoClient:
    """Stands in for the Sonos connection: always connected, records plays."""

    def __init__(self, session, ip, uid):
        self.ip = ip
        self.player_id = uid
        self.connected = False
        self.plays = []

    async def connect(self):
        self.connected = True

    async def close(self):
        self.connected = False

    async def play(self, url, volume):
        self.plays.append({"url": url, "volume": volume})


def demo_probe(ip):
    return {"uid": f"RINCON_DEMO{ip.rsplit('.', 1)[-1]}01400", "name": f"Box {ip}"}


def demo_discover():
    return [
        {"name": "Küche", "ip": "192.0.2.22", "uid": "RINCON_DEMO2201400", "model": "Sonos One"},
        {"name": "Schlafzimmer", "ip": "192.0.2.25", "uid": "RINCON_DEMO2501400", "model": "Sonos Era 100"},
    ]


def fill_demo_data(app, data_dir: Path, sounds_dir: Path) -> None:
    app.state.auth.set_password("demo-passwort")
    store = app.state.store

    boxes = {}
    for name, ip in BOXES:
        box = Box(id=store.new_box_id(), name=name, ip=ip, uid=demo_probe(ip)["uid"])
        store.state.boxes.append(box)
        boxes[name] = box

    # An uploaded gong, so the Gongs tab shows rename and delete buttons.
    upload_dir = data_dir / "sounds"
    upload_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(sounds_dir / "westminster.wav", upload_dir / "a1b2c3d4.wav")
    with wave.open(str(upload_dir / "a1b2c3d4.wav"), "rb") as handle:
        duration = round(handle.getnframes() / handle.getframerate(), 2)
    store.state.sounds.append(UploadedSound(id="a1b2c3d4", name="Klingel Opa", file="a1b2c3d4.wav", duration=duration))

    store.state.advertise_host = "192.0.2.5"
    store.state.profiles = [
        Profile(
            id="haustuer", name="Haustür", sound="ding-dong", cooldown_s=3, token="Qm7vK2xLp9TnA4sRwZ1bYg",
            members=[Member(box=boxes["Wohnzimmer"].id, volume=35), Member(box=boxes["Küche"].id, volume=40),
                     Member(box=boxes["Flur"].id, volume=30)],
        ),
        Profile(
            id="gartentor", name="Gartentor", sound="dreiklang", cooldown_s=5, token="Hd3cN8fUe6JkW0aXoPq5Vt",
            members=[Member(box=boxes["Küche"].id, volume=30), Member(box=boxes["Büro"].id, volume=25)],
        ),
    ]
    store.save()

    now = datetime.now().astimezone()

    def ev(ago: timedelta, source, profile, sound, results):
        return {
            "time": (now - ago).isoformat(timespec="seconds"),
            "source": source, "profile": profile, "sound": sound, "results": results,
        }

    def ok(box, ms):
        return {"box": box, "ok": True, "ms": ms, "error": None}

    events = [
        ev(timedelta(days=5, hours=3), "loxone", "Haustür", "Ding-Dong", [ok("Wohnzimmer", 142), ok("Küche", 168), ok("Flur", 155)]),
        ev(timedelta(days=4, hours=1), "test", "Gartentor", "Dreiklang", [ok("Küche", 187), ok("Büro", 231)]),
        ev(timedelta(days=2, hours=6), "loxone", "Haustür", "Ding-Dong", [ok("Wohnzimmer", 126), ok("Küche", 149), ok("Flur", 138)]),
        ev(timedelta(days=1, hours=2), "loxone", "Gartentor", "Dreiklang", [
            ok("Küche", 204), {"box": "Büro", "ok": False, "ms": None, "error": "Box nicht erreichbar"}]),
        ev(timedelta(hours=5), "loxone", "Haustür", "Ding-Dong", [ok("Wohnzimmer", 133), ok("Küche", 259), ok("Flur", 171)]),
        ev(timedelta(minutes=40), "test", "Haustür", "Ding-Dong", [ok("Wohnzimmer", 121), ok("Küche", 146), ok("Flur", 160)]),
    ]
    lines = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events)
    app.state.history.path.write_text(lines, encoding="utf-8")


# ------------------------------------------------------------------- helpers


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def find_browser() -> str:
    override = os.environ.get("BROWSER_PATH")
    if override:
        return override
    candidates = []
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            candidates.append(Path(base) / "Microsoft/Edge/Application/msedge.exe")
            candidates.append(Path(base) / "Google/Chrome/Application/chrome.exe")
    for path in candidates:
        if path.is_file():
            return str(path)
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "microsoft-edge", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    sys.exit("Kein Browser gefunden. Pfad in BROWSER_PATH angeben.")


def stop_process(proc: subprocess.Popen) -> None:
    """Stops only the process tree that was started here."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


class Cdp:
    """Minimal DevTools protocol client for one page."""

    def __init__(self, ws):
        self.ws = ws
        self.next_id = 0
        self.pending: dict[int, asyncio.Future] = {}
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        async for msg in self.ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            data = json.loads(msg.data)
            future = self.pending.pop(data.get("id"), None)
            if future and not future.done():
                if "error" in data:
                    future.set_exception(RuntimeError(str(data["error"])))
                else:
                    future.set_result(data.get("result", {}))

    async def call(self, method: str, **params):
        self.next_id += 1
        future = asyncio.get_running_loop().create_future()
        self.pending[self.next_id] = future
        await self.ws.send_str(json.dumps({"id": self.next_id, "method": method, "params": params}))
        return await asyncio.wait_for(future, 30)

    async def eval(self, expression: str):
        result = await self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"].get("text", "evaluate failed") + " in " + expression)
        return result["result"].get("value")

    async def wait_for(self, expression: str, timeout: float = 15):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if await self.eval(expression):
                return
            await asyncio.sleep(0.1)
        raise TimeoutError(f"Bedingung nicht erfüllt: {expression}")

    async def click(self, selector: str, text: str | None = None, within: str | None = None):
        script = f"""(() => {{
          const scope = {json.dumps(within)} ? [...document.querySelectorAll({json.dumps(within)})] : [document];
          for (const root of scope) {{
            for (const el of root.querySelectorAll({json.dumps(selector)})) {{
              if ({json.dumps(text)} === null || el.textContent.includes({json.dumps(text)})) {{ el.click(); return true; }}
            }}
          }}
          return false;
        }})()"""
        if not await self.eval(script):
            raise RuntimeError(f"Element nicht gefunden: {selector} {text or ''}")


async def settle(cdp: Cdp) -> None:
    """Waits until no spinner is visible and fonts and layout are done."""
    await cdp.wait_for("!document.querySelector('.spinner, .loading')")
    await cdp.eval("document.fonts.ready.then(() => true)")
    await asyncio.sleep(0.3)


async def shoot(cdp: Cdp, path: Path, width: int, scale: float = 1, mobile: bool = False) -> None:
    """Sizes the viewport to the page content and captures it."""
    await cdp.call("Emulation.setDeviceMetricsOverride", width=width, height=200, deviceScaleFactor=scale, mobile=mobile)
    height = await cdp.eval("Math.ceil(document.documentElement.scrollHeight)")
    height = min(max(height, 300), 4000)
    await cdp.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=scale, mobile=mobile)
    # Forms focus their first field; the focus ring would look like a misaligned input.
    await cdp.eval("document.activeElement && document.activeElement.blur()")
    await asyncio.sleep(0.2)
    shot = await cdp.call("Page.captureScreenshot", format="png", captureBeyondViewport=False)
    path.write_bytes(base64.b64decode(shot["data"]))


async def capture(base_url: str, debug_port: int, cookie: str, out: Path) -> list[Path]:
    written: list[Path] = []
    async with aiohttp.ClientSession() as http:
        for _ in range(100):
            try:
                async with http.get(f"http://127.0.0.1:{debug_port}/json/list") as resp:
                    targets = [t for t in await resp.json() if t.get("type") == "page"]
                if targets:
                    break
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(0.2)
        else:
            raise RuntimeError("Browser startet nicht")
        async with http.ws_connect(targets[0]["webSocketDebuggerUrl"], max_msg_size=0) as ws:
            cdp = Cdp(ws)
            await cdp.call("Page.enable")
            await cdp.call("Network.enable")
            await cdp.call("Network.setCacheDisabled", cacheDisabled=True)
            await cdp.call(
                "Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}]
            )
            await cdp.call("Network.setCookie", name=COOKIE_NAME, value=cookie, url=base_url)
            await cdp.call("Page.navigate", url=base_url + "/")

            async def go_tab(tab: str, ready: str):
                await cdp.wait_for("!!document.querySelector('[data-tab=\"profile\"]')")
                await cdp.click(f'[data-tab="{tab}"]')
                await cdp.wait_for(ready)
                await settle(cdp)

            async def save(name: str, width: int = DESKTOP_WIDTH, scale: float = 1, mobile: bool = False):
                path = out / name
                await shoot(cdp, path, width, scale, mobile)
                written.append(path)

            await cdp.call("Emulation.setDeviceMetricsOverride", width=DESKTOP_WIDTH, height=900, deviceScaleFactor=1, mobile=False)
            await go_tab("profile", "document.querySelectorAll('article.card').length === 2")
            await cdp.wait_for("document.querySelector('#conn')?.textContent.includes('4/4')")
            await save("profile.png")

            await cdp.click('[data-action="profile-edit"]', within="article.card")
            await cdp.wait_for("!!document.querySelector('#pf-name')")
            await settle(cdp)
            await cdp.eval("document.activeElement && document.activeElement.blur()")
            await save("profil-bearbeiten.png")

            await go_tab("boxen", "document.querySelectorAll('.list .item').length === 4")
            await save("boxen.png")
            await cdp.click('[data-action="discover"]')
            await cdp.wait_for("!!document.querySelector('.discover-list')")
            await settle(cdp)
            await save("boxen-suche.png")

            await go_tab("gongs", "document.querySelectorAll('.list .item').length === 5")
            await save("gongs.png")

            await go_tab("historie", "document.querySelectorAll('tbody tr').length === 6")
            await save("historie.png")

            await go_tab("einstellungen", "!!document.querySelector('#st-host')")
            await save("einstellungen.png")

            await go_tab("profile", "document.querySelectorAll('article.card').length === 2")
            await save("handy-profil.png", MOBILE_WIDTH, scale=2, mobile=True)
    return written


# ---------------------------------------------------------------------- main


def run(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="sonos-shots-"))
    server = thread = browser = None
    try:
        data_dir = tmp / "data"
        sounds_dir = ROOT / "sounds"
        app = create_app(
            data_dir=data_dir,
            sounds_dir=sounds_dir,
            client_factory=DemoClient,
            probe=demo_probe,
            discover=demo_discover,
            detect_ip=lambda: "192.0.2.5",
            seed_env=False,
        )
        fill_demo_data(app, data_dir, sounds_dir)

        port = free_port()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Server startet nicht")
        base_url = f"http://127.0.0.1:{port}"

        debug_port = free_port()
        browser = subprocess.Popen(
            [
                find_browser(), "--headless=new", f"--remote-debugging-port={debug_port}",
                f"--user-data-dir={tmp / 'browser'}", "--no-first-run", "--no-default-browser-check",
                "--hide-scrollbars", "--disable-gpu", "--force-color-profile=srgb", "about:blank",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return asyncio.run(capture(base_url, debug_port, app.state.auth.make_cookie(), out))
    finally:
        if browser is not None:
            stop_process(browser)
        if server is not None:
            server.should_exit = True
            thread.join(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "screenshots")
    args = parser.parse_args()
    for path in run(args.out):
        print(f"{path} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
