"""One-time pairing codes: how the desktop inherits a web session.

The desktop cannot open Google's consent page, but the web client can. The
flow, modelled on GitHub CLI's device pairing:

1. the user signs in on the web — password or Google — and clicks
   "Pair desktop app";
2. the server issues a short-lived, one-time code bound to that identity;
3. the user types the code into the desktop login window;
4. the desktop redeems it and receives the same account, so a Google-verified
   identity signs into the workstation without the desktop ever seeing a
   browser.

Codes are random, single-use, expire in 10 minutes, and a user may hold at
most a few live codes at once.
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any

CODE_TTL_SECONDS = 600          # 10 minutes
MAX_LIVE_PER_IDENTITY = 3
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no look-alike glyphs


class PairingError(Exception):
    """Raised for unknown, expired, or over-quota pairing codes."""


class PairingRegistry:
    """In-memory code store; pairing is deliberately not persisted.

    A pairing code is a transient handshake, not a credential: losing it to a
    restart costs the user ten seconds, whereas storing codes would give them
    a lifetime beyond the moment they were meant for.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._codes: dict[str, dict[str, Any]] = {}

    def issue_code(self, identity: dict[str, Any], *,
                   label: str = "Desktop workstation") -> dict[str, Any]:
        with self._lock:
            # Bound how many live codes one identity may hold.
            live = [c for c, e in self._codes.items()
                    if e["identity"].get("sub") == identity.get("sub")]
            if len(live) >= MAX_LIVE_PER_IDENTITY:
                raise PairingError(
                    "Too many pending pairing codes — use one or wait for it "
                    "to expire.")
            while True:
                code = "-".join(
                    "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
                    for _ in range(2))
                if code not in self._codes:
                    break
            now = time.time()
            self._codes[code] = {
                "identity": identity,
                "label": label,
                "issued_at": now,
                "expires_at": now + CODE_TTL_SECONDS,
            }
            return {
                "code": code,
                "expires_in": CODE_TTL_SECONDS,
                "label": label,
            }

    def redeem_code(self, code: str) -> dict[str, Any]:
        code = (code or "").strip().upper()
        with self._lock:
            entry = self._codes.pop(code, None)
        if entry is None:
            raise PairingError("Unknown pairing code.")
        if entry["expires_at"] < time.time():
            raise PairingError("This pairing code has expired — generate a new one.")
        return entry["identity"]

    def purge(self) -> int:
        """Drop expired codes; returns how many were removed."""
        now = time.time()
        with self._lock:
            stale = [c for c, e in self._codes.items()
                     if e["expires_at"] < now]
            for code in stale:
                del self._codes[code]
        return len(stale)


pairing = PairingRegistry()
