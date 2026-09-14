"""Time source.

Timestamps are generated through a clock object rather than by calling
``datetime.now()`` at the point of use, so tests can pin or advance time and
assert on stored values.

Timestamps are written as ``YYYY-MM-DD HH:MM:SS`` in UTC. That is the format
SQLite's own ``CURRENT_TIMESTAMP`` produces, which keeps rows written by the
pre-refactor application correctly ordered alongside new ones.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

#: Storage format for timestamps. Matches SQLite's ``CURRENT_TIMESTAMP``.
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


@runtime_checkable
class Clock(Protocol):
    """Anything that can report the current moment.

    Three methods rather than one, because timestamps are stored as strings and
    formatting them at every call site would mean repeating the same conversion in
    a dozen places — and getting it wrong in one of them.
    """

    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC datetime."""
        ...

    def timestamp(self) -> str:
        """Return the current moment in MedFlow's storage format."""
        ...

    def today(self) -> str:
        """Return the current date as ``YYYY-MM-DD``."""
        ...


class SystemClock:
    """The real clock."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def timestamp(self) -> str:
        return format_timestamp(self.now())

    def today(self) -> str:
        return self.timestamp()[:10]


class FixedClock:
    """A clock frozen at a chosen moment, for tests.

    Use :meth:`advance` to move it forward so a test can prove that an update
    changed a record's ``updated_at``.
    """

    def __init__(self, moment: datetime | None = None) -> None:
        if moment is None:
            moment = datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        self._moment = moment

    def now(self) -> datetime:
        return self._moment

    def timestamp(self) -> str:
        return format_timestamp(self._moment)

    def today(self) -> str:
        return self.timestamp()[:10]

    def advance(self, seconds: float = 0, **kwargs: float) -> datetime:
        """Move the clock forward and return the new moment."""
        self._moment += timedelta(seconds=seconds, **kwargs)
        return self._moment


def format_timestamp(moment: datetime) -> str:
    """Render a datetime in MedFlow's storage format."""
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
    return moment.strftime(TIMESTAMP_FORMAT)


def parse_timestamp(value: str) -> datetime:
    """Parse a stored timestamp back into an aware UTC datetime."""
    parsed = datetime.strptime(value, TIMESTAMP_FORMAT)
    return parsed.replace(tzinfo=timezone.utc)


def utc_now_timestamp() -> str:
    """Convenience for call sites that genuinely have no clock to hand."""
    return format_timestamp(SystemClock().now())
