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
    """Format timestamps in EAT with compatibility for legacy naive values."""
    if value is None or not str(value).strip():
        return ""
    if isinstance(value, datetime):
        parsed = value
        # PostgreSQL TIMESTAMP (without time zone) returns a naive datetime.
        # New job timestamps are written as EAT wall-clock values into that
        # column, so interpret datetime objects as EAT rather than UTC.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=EAT)
    else:
        raw = str(value).strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return raw
        # Legacy SQLite CURRENT_TIMESTAMP strings are UTC and have no offset.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(EAT).replace(microsecond=0).strftime("%d %b %Y %H:%M EAT")
