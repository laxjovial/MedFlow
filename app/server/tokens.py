"""HMAC-signed bearer tokens with expiry — no external dependency.

Tokens are ``base64(payload).base64(signature)`` where the payload carries
the user id, username, role, and an expiry timestamp. The signing secret is
generated once per server installation and stored beside the database, so
tokens survive server restarts but are useless to another facility's copy.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

_TOKEN_TTL_SECONDS = 12 * 3600


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


class TokenError(Exception):
    """Raised for expired, malformed, or forged tokens."""


def issue(payload: dict, secret: bytes, ttl: int = _TOKEN_TTL_SECONDS) -> str:
    body = dict(payload)
    body["exp"] = int(time.time()) + ttl
    raw = json.dumps(body, sort_keys=True).encode()
    sig = hmac.new(secret, raw, hashlib.sha256).digest()
    return f"{_b64(raw)}.{_b64(sig)}"


def verify(token: str, secret: bytes) -> dict:
    try:
        raw_b64, sig_b64 = token.split(".", 1)
        raw = _unb64(raw_b64)
        expected = hmac.new(secret, raw, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(sig_b64)):
            raise TokenError("bad signature")
        body = json.loads(raw)
        if int(body.get("exp", 0)) < time.time():
            raise TokenError("token expired")
        return body
    except (ValueError, KeyError, TypeError) as exc:
        raise TokenError("malformed token") from exc


def load_or_create_secret(path: Path) -> bytes:
    """One secret per installation, stored beside the database."""
    path = Path(path)
    if path.exists():
        return path.read_bytes().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32).encode()
    path.write_bytes(secret)
    try:
        import os
        os.chmod(path, 0o600)
    except OSError:
        pass
    return secret
