"""Backup and restore of configuration and uploaded sounds as a ZIP file."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from .sounds import SOUND_FILE
from .store import State

MAX_RESTORE_BYTES = 200 * 1024 * 1024


class BackupError(Exception):
    pass


def make_backup(state: State, upload_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("config.json", state.model_dump_json(indent=2))
        for item in state.sounds:
            path = upload_dir / item.file
            if path.is_file():
                archive.write(path, f"sounds/{item.file}")
    return buffer.getvalue()


def read_backup(data: bytes) -> tuple[State, dict[str, bytes]]:
    """Validates a backup and returns the configuration and the sound files."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise BackupError("Die Datei ist kein gültiges Backup (ZIP)") from None
    with archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_RESTORE_BYTES:
            raise BackupError("Das Backup ist zu groß")
        try:
            state = State.model_validate_json(archive.read("config.json"))
        except KeyError:
            raise BackupError("Das Backup enthält keine config.json") from None
        except ValueError:
            raise BackupError("Die config.json im Backup ist ungültig") from None
        files = {}
        for info in archive.infolist():
            name = info.filename
            if name.startswith("sounds/") and SOUND_FILE.match(name[len("sounds/"):]):
                files[name[len("sounds/"):]] = archive.read(info)
    state.sounds = [s for s in state.sounds if s.file in files and SOUND_FILE.match(s.file)]
    return state, files


def apply_files(files: dict[str, bytes], upload_dir: Path) -> None:
    upload_dir.mkdir(parents=True, exist_ok=True)
    for old in upload_dir.glob("*.mp3"):
        old.unlink(missing_ok=True)
    for name, content in files.items():
        (upload_dir / name).write_bytes(content)
