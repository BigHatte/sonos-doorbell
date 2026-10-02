"""Single shared password with signed session cookies."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

from .store import atomic_write

COOKIE_NAME = "sd_session"
SESSION_SECONDS = 30 * 24 * 3600
MIN_PASSWORD = 8


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)


class Auth:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "auth.json"

    def _load(self) -> dict | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if data.get("password_hash") and data.get("secret") else None
        except (OSError, ValueError):
            return None

    @property
    def configured(self) -> bool:
        return self._load() is not None

    def set_password(self, password: str) -> None:
        """Stores a new password and a fresh secret, which invalidates all sessions."""
        salt = secrets.token_bytes(16)
        stored = f"scrypt${salt.hex()}${_hash(password, salt).hex()}"
        atomic_write(self.path, json.dumps({"password_hash": stored, "secret": secrets.token_hex(32)}))

    def verify(self, password: str) -> bool:
        data = self._load()
        if data is None:
            return False
        try:
            _, salt, expected = data["password_hash"].split("$")
            actual = _hash(password, bytes.fromhex(salt))
            return hmac.compare_digest(actual, bytes.fromhex(expected))
        except ValueError:
            return False

    def make_cookie(self) -> str:
        data = self._load()
        expiry = str(int(time.time()) + SESSION_SECONDS)
        return f"{expiry}.{self._sign(data['secret'], expiry)}"

    def valid_cookie(self, value: str | None) -> bool:
        data = self._load()
        if not value or data is None:
            return False
        expiry, _, signature = value.partition(".")
        if not expiry.isdigit() or int(expiry) < time.time():
            return False
        return hmac.compare_digest(signature, self._sign(data["secret"], expiry))

    @staticmethod
    def _sign(secret: str, expiry: str) -> str:
        return hmac.new(bytes.fromhex(secret), expiry.encode(), hashlib.sha256).hexdigest()
