"""Built-in and uploaded chime sounds, plus the ffmpeg processing of uploads."""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import shutil
import wave
from dataclasses import dataclass
from pathlib import Path

from .store import Store, UploadedSound

log = logging.getLogger(__name__)

SOUND_FILE = re.compile(r"^[A-Za-z0-9_.-]+\.(mp3|wav)$")
BUILTINS = {
    "ding-dong": "Ding-Dong",
    "dreiklang": "Dreiklang",
    "einzelton": "Einzelton",
    "westminster": "Westminster",
}
FFMPEG_FILTER = (
    "silenceremove=start_periods=1:start_threshold=-50dB,"
    "loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=out:st=9:d=1"
)
FFMPEG_TIMEOUT_S = 120


class SoundError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass
class Sound:
    id: str
    name: str
    file: str
    path: Path
    builtin: bool
    duration: float | None


def _wav_duration(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as handle:
            return round(handle.getnframes() / handle.getframerate(), 2)
    except Exception:
        return None


class SoundLibrary:
    def __init__(self, store: Store, builtin_dir: Path, upload_dir: Path):
        self._store = store
        self.builtin_dir = builtin_dir
        self.upload_dir = upload_dir
        self._builtin_durations: dict[str, float | None] = {}

    def builtin_ids(self) -> set[str]:
        return set(BUILTINS)

    def all(self) -> list[Sound]:
        sounds = []
        for sound_id, name in BUILTINS.items():
            path = self.builtin_dir / f"{sound_id}.wav"
            if sound_id not in self._builtin_durations and path.is_file():
                self._builtin_durations[sound_id] = _wav_duration(path)
            sounds.append(Sound(sound_id, name, path.name, path, True, self._builtin_durations.get(sound_id)))
        for item in self._store.state.sounds:
            sounds.append(Sound(item.id, item.name, item.file, self.upload_dir / item.file, False, item.duration))
        return sounds

    def get(self, sound_id: str) -> Sound | None:
        return next((s for s in self.all() if s.id == sound_id), None)

    def exists(self, sound_id: str) -> bool:
        sound = self.get(sound_id)
        return sound is not None and sound.path.is_file()

    def file_path(self, filename: str) -> Path | None:
        """Resolves a public file name to a built-in or uploaded file."""
        if not SOUND_FILE.match(filename):
            return None
        for folder in (self.builtin_dir, self.upload_dir):
            path = folder / filename
            if path.is_file():
                return path
        return None

    async def add_upload(self, source: Path, name: str) -> UploadedSound:
        """Converts an uploaded file to a normalized MP3 and registers it."""
        if shutil.which("ffmpeg") is None:
            raise SoundError(503, "ffmpeg ist nicht installiert")
        sound_id = secrets.token_hex(4)
        target = self.upload_dir / f"{sound_id}.mp3"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        try:
            await self._run(
                "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(source),
                "-af", FFMPEG_FILTER, "-t", "10", "-ar", "44100", "-ac", "2",
                "-c:a", "libmp3lame", "-b:a", "192k", str(target),
            )
            duration = await self._duration(target)
        except SoundError:
            target.unlink(missing_ok=True)
            raise
        if not duration:
            target.unlink(missing_ok=True)
            raise SoundError(400, "Die Datei enthält kein hörbares Audio")
        item = UploadedSound(id=sound_id, name=name, file=target.name, duration=duration)
        self._store.state.sounds.append(item)
        self._store.save()
        return item

    def remove(self, item: UploadedSound) -> None:
        self._store.state.sounds.remove(item)
        self._store.save()
        (self.upload_dir / item.file).unlink(missing_ok=True)

    async def _run(self, *cmd: str) -> bytes:
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            out, err = await asyncio.wait_for(process.communicate(), FFMPEG_TIMEOUT_S)
        except FileNotFoundError:
            raise SoundError(503, "ffmpeg ist nicht installiert") from None
        except asyncio.TimeoutError:
            process.kill()
            raise SoundError(400, "Die Verarbeitung der Datei hat zu lange gedauert") from None
        if process.returncode != 0:
            log.warning("ffmpeg fehlgeschlagen: %s", err.decode(errors="replace")[-500:])
            raise SoundError(400, "Die Datei konnte nicht verarbeitet werden (kein gültiges Audioformat?)")
        return out

    async def _duration(self, path: Path) -> float | None:
        out = await self._run(
            "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)
        )
        try:
            return round(float(out.decode().strip()), 2)
        except ValueError:
            return None
