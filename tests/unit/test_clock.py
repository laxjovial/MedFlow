"""The clock.

Time is injectable so that a stored timestamp can be asserted on. That only works
if the formatting is exact, so most of these tests are about the one thing the
clock promises: whatever it returns is what SQLite's ``CURRENT_TIMESTAMP`` would
have written.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from app.core.clock import (
    TIMESTAMP_FORMAT,
    Clock,
    FixedClock,
    SystemClock,
    format_timestamp,
    parse_timestamp,
    utc_now_timestamp,
)

#: What SQLite writes: "2026-03-04 10:30:00".
STORAGE_SHAPE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


class TestFormatTimestamp:
    def test_an_aware_utc_moment_is_formatted_as_stored(self) -> None:
        moment = datetime(2026, 3, 4, 10, 30, 0, tzinfo=timezone.utc)
        assert format_timestamp(moment) == "2026-03-04 10:30:00"

    def test_the_format_matches_sqlite_current_timestamp(self) -> None:
        # Legacy rows were written by SQLite itself. If these ever diverge,
        # ordering across the migration boundary silently breaks.
        import sqlite3

        connection = sqlite3.connect(":memory:")
        try:
            stored = connection.execute("SELECT CURRENT_TIMESTAMP").fetchone()[0]
        finally:
            connection.close()

        assert format_timestamp(datetime.now(timezone.utc))[:16] == stored[:16]
        assert " " in stored  # SQLite's format has no "T"

    def test_another_timezone_is_converted_not_relabelled(self) -> None:
        # 12:30 in Nairobi is 09:30 UTC. Writing 12:30 would make a record look
        # like it happened three hours later than it did.
        nairobi = timezone(timedelta(hours=3))
        moment = datetime(2026, 3, 4, 12, 30, 0, tzinfo=nairobi)

        assert format_timestamp(moment) == "2026-03-04 09:30:00"

    def test_a_naive_moment_is_taken_at_face_value(self) -> None:
        # Naive input is ambiguous, not wrong — treating it as UTC is the least
        # surprising reading, and the alternative would be guessing an offset.
        assert format_timestamp(datetime(2026, 3, 4, 10, 30, 0)) == "2026-03-04 10:30:00"

    def test_microseconds_are_dropped_so_rows_stay_sorted_by_string(self) -> None:
        moment = datetime(2026, 3, 4, 10, 30, 0, 123456, tzinfo=timezone.utc)
        assert format_timestamp(moment) == "2026-03-04 10:30:00"


class TestParseTimestamp:
    def test_a_stored_string_round_trips(self) -> None:
        moment = datetime(2026, 3, 4, 10, 30, 0, tzinfo=timezone.utc)
        assert parse_timestamp(format_timestamp(moment)) == moment

    def test_the_result_is_timezone_aware(self) -> None:
        parsed = parse_timestamp("2026-03-04 10:30:00")

        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timedelta(0)

    def test_a_malformed_string_raises_rather_than_guessing(self) -> None:
        with pytest.raises(ValueError):
            parse_timestamp("04/03/2026 10:30")


class TestSystemClock:
    def test_now_is_timezone_aware_utc(self) -> None:
        moment = SystemClock().now()

        assert moment.tzinfo is not None
        assert moment.utcoffset() == timedelta(0)

    def test_the_timestamp_is_in_the_storage_shape(self) -> None:
        assert STORAGE_SHAPE.match(SystemClock().timestamp())

    def test_today_matches_the_first_ten_characters_of_the_timestamp(self) -> None:
        # One implementation, so the two can never disagree about which day it is.
        clock = SystemClock()
        assert clock.today() == clock.timestamp()[:10]

    def test_today_is_an_iso_date(self) -> None:
        assert datetime.fromisoformat(SystemClock().today())


class TestFixedClock:
    def test_the_default_moment_is_documented_and_stable(self) -> None:
        clock = FixedClock()

        assert clock.now() == datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
        assert clock.timestamp() == "2026-01-01 09:00:00"
        assert clock.today() == "2026-01-01"

    def test_a_naive_moment_is_interpreted_as_utc(self) -> None:
        clock = FixedClock(datetime(2026, 3, 4, 10, 30, 0))

        assert clock.now().tzinfo is not None
        assert clock.timestamp() == "2026-03-04 10:30:00"

    def test_time_does_not_move_on_its_own(self) -> None:
        clock = FixedClock()
        first = clock.timestamp()
        second = clock.timestamp()

        assert first == second

    def test_advance_moves_the_clock_and_reports_the_new_moment(self) -> None:
        clock = FixedClock(datetime(2026, 3, 4, 10, 30, 0))

        returned = clock.advance(seconds=90)

        assert returned == datetime(2026, 3, 4, 10, 31, 30, tzinfo=timezone.utc)
        assert clock.timestamp() == "2026-03-04 10:31:30"

    def test_advance_accepts_datetime_units(self) -> None:
        clock = FixedClock(datetime(2026, 3, 4, 10, 30, 0))

        clock.advance(days=1, hours=2)

        assert clock.timestamp() == "2026-03-05 12:30:00"

    def test_advancing_by_nothing_still_returns_the_moment(self) -> None:
        clock = FixedClock(datetime(2026, 3, 4, 10, 30, 0))
        assert clock.advance() == clock.now()

    def test_advancing_across_midnight_moves_today(self) -> None:
        # Used by tests that check "created today" counts, so this is the
        # behaviour they depend on.
        clock = FixedClock(datetime(2026, 3, 4, 23, 59, 30))

        clock.advance(seconds=60)

        assert clock.today() == "2026-03-05"


class TestClockProtocol:
    @pytest.mark.parametrize("clock", [SystemClock(), FixedClock()])
    def test_both_implementations_satisfy_the_protocol(self, clock: object) -> None:
        # Checked at runtime so a new implementation missing a method fails here
        # rather than at whichever call site happens to reach for it first.
        assert isinstance(clock, Clock)


class TestConvenience:
    def test_utc_now_timestamp_is_in_the_storage_shape(self) -> None:
        assert STORAGE_SHAPE.match(utc_now_timestamp())

    def test_the_storage_format_constant_is_the_one_sqlite_uses(self) -> None:
        assert TIMESTAMP_FORMAT == "%Y-%m-%d %H:%M:%S"
