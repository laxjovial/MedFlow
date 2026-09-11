"""Date and time helpers shared by services, repositories, and the API."""

from __future__ import annotations

from datetime import datetime, timezone

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_iso(dt: datetime | None) -> str | None:
    return dt.strftime(ISO_FORMAT) if dt else None


def from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, ISO_FORMAT)
    except ValueError:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None


def humanize(value: str | None) -> str:
    """Render an ISO timestamp for humans: '2026-09-11 10:42'."""
    dt = from_iso(value) if isinstance(value, str) else value
    if not dt:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M")


def relative_label(iso_value: str | None, now: datetime | None = None) -> str:
    """Compact relative label like '3m ago' or 'in 2h' for dashboards."""
    dt = from_iso(iso_value)
    if not dt:
        return "—"
    now = now or utcnow()
    delta = dt - now
    seconds = int(delta.total_seconds())
    past = seconds < 0
    seconds = abs(seconds)
    if seconds < 60:
        text = f"{seconds}s"
    elif seconds < 3600:
        text = f"{seconds // 60}m"
    elif seconds < 86400:
        text = f"{seconds // 3600}h"
    else:
        text = f"{seconds // 86400}d"
    return f"{text} ago" if past else f"in {text}"
