"""Shared clock utilities for the timetable module.

All timetable audit timestamps and generated-at labels use Kenya/East Africa
local time (Africa/Nairobi, UTC+03:00), independent of the host server timezone.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


EAT = ZoneInfo("Africa/Nairobi")


def now_eat() -> str:
    """Return the current East Africa time as an ISO-8601 timestamp with offset."""
    return datetime.now(EAT).replace(microsecond=0).isoformat()


def format_eat(value: object) -> str:
    """Format stored timestamps in EAT, treating legacy naive DB values as UTC."""
    if value is None or not str(value).strip():
        return ""
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value).strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return raw
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(EAT).replace(microsecond=0).strftime("%d %b %Y %H:%M EAT")
