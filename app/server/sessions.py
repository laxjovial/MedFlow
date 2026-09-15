"""Session policy: how long a sign-in lasts and how it renews.

Session length is an operator decision, not a hardcoded constant — a busy
outpatient desk and a night-shift ward want different trade-offs between
convenience and re-authentication. Defaults (12-hour sessions, 30-day
remember-me, rolling refresh) fit a typical clinic day; the administrator
changes them in Settings and the change applies to every future sign-in.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.runtime_config import SessionConfig


@dataclass(frozen=True)
class SessionPolicy:
    normal_ttl: int          # seconds for an ordinary sign-in
    remember_ttl: int        # seconds when "keep me signed in" is ticked
    sliding: bool            # renew expiry while the session is in use


def policy_from(cfg: SessionConfig | None) -> SessionPolicy:
    cfg = cfg or SessionConfig()
    return SessionPolicy(
        normal_ttl=max(1, int(cfg.token_ttl_hours)) * 3600,
        remember_ttl=max(1, int(cfg.remember_me_days)) * 86400,
        sliding=bool(cfg.sliding_refresh),
    )


def ttl_for(policy: SessionPolicy, remember: bool) -> int:
    return policy.remember_ttl if remember else policy.normal_ttl


def refreshed_payload(payload: dict, policy: SessionPolicy) -> dict | None:
    """Renew an existing token's expiry, preserving its identity claims.

    Returns a NEW payload when the session should roll forward, or None when
    the caller should keep its current token (remembered sessions always
    renew; ordinary ones only when the operator enabled sliding refresh).
    """
    if not payload.get("remember") and not policy.sliding:
        return None
    body = dict(payload)
    body["exp"] = int(time.time()) + ttl_for(policy, bool(payload.get("remember")))
    return body
