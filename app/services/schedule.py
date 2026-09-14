"""Schedule service — re-exports the appointment workflows.

Appointments live in :mod:`app.services.records` alongside the chart they
belong to clinically; this module gives the UI and API a stable import
point (`from app.services.schedule import ScheduleService`) without
duplicating logic.
"""

from __future__ import annotations

from app.services.records import RecordsService

ScheduleService = RecordsService

__all__ = ["ScheduleService"]
