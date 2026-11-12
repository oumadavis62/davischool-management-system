"""Shared clock utilities for the timetable module.

All timetable audit timestamps and generated-at labels use Kenya/East Africa
local time (Africa/Nairobi, UTC+03:00), independent of the host server timezone.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


EAT = ZoneInfo("Africa/Nairobi")


def now_eat() -> str:
    """Return the current East Africa time as an ISO-8601 timestamp with offset."""
    return datetime.now(EAT).replace(microsecond=0).isoformat()
