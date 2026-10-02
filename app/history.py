"""Ring history as JSON lines, kept for 30 days."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .store import atomic_write

log = logging.getLogger(__name__)

RETENTION = timedelta(days=30)
MAX_ENTRIES = 1000


class History:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "history.jsonl"

    def add(self, source: str, profile: str | None, sound: str, results: list[dict]) -> None:
        event = {
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": source,
            "profile": profile,
            "sound": sound,
            "results": results,
        }
        try:
            events = self._read()
            events.append(event)
            cutoff = datetime.now().astimezone() - RETENTION
            events = [e for e in events if self._time(e) >= cutoff]
            atomic_write(self.path, "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events))
        except OSError:
            log.exception("Historie konnte nicht geschrieben werden")

    def list(self, limit: int = MAX_ENTRIES) -> list[dict]:
        return list(reversed(self._read()))[:limit]

    def _read(self) -> list[dict]:
        events = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return events
        for line in lines:
            try:
                event = json.loads(line)
                self._time(event)
                events.append(event)
            except (ValueError, KeyError, TypeError):
                continue
        return events

    @staticmethod
    def _time(event: dict) -> datetime:
        return datetime.fromisoformat(event["time"])
