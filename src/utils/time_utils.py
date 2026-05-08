# src/utils/time_utils.py
"""
Centralized timezone utilities for SurveilX.

Uses the system's LOCAL timezone for all timestamps (display and storage).
This ensures the UI, Neon, Chroma, and Cloudinary all show the same local time
without any UTC conversion confusion.
"""
from datetime import datetime, timezone, timedelta
import time as _time

# System local UTC offset (e.g. PKT = UTC+5)
_LOCAL_OFFSET = timedelta(seconds=-_time.timezone if not _time.daylight else -_time.altzone)
LOCAL_TZ = timezone(_LOCAL_OFFSET)


def utcnow() -> datetime:
    """Return the current local system time as a timezone-aware datetime.
    
    Despite the name (kept for backward compatibility), this now returns
    LOCAL system time with the local timezone offset attached.
    This matches what gets stored in Neon and displayed in the UI.
    """
    return datetime.now(LOCAL_TZ)


def utcnow_naive() -> datetime:
    """Return current local time WITHOUT tzinfo.
    Used for SQLAlchemy TIMESTAMP columns that don't carry timezone info.
    """
    return datetime.now(LOCAL_TZ).replace(tzinfo=None)


def to_utc(dt: datetime) -> datetime:
    """Normalise a datetime to the local timezone.
    - If naive  → assume local time, attach LOCAL_TZ.
    - If aware  → convert to local timezone.
    """
    if dt is None:
        return utcnow()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(LOCAL_TZ)


def utc_iso(dt: datetime = None) -> str:
    """Return an ISO-8601 string in local timezone."""
    return to_utc(dt or utcnow()).isoformat()


def parse_utc(iso_str: str) -> datetime:
    """Parse an ISO-8601 string → local timezone-aware datetime.
    Handles strings with or without timezone suffix.
    """
    if not iso_str:
        raise ValueError("Empty ISO string")
    iso_str = iso_str.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(iso_str)
    return to_utc(dt)


def utc_from_ts_str(ts_str: str, fmt: str = "%Y%m%d_%H%M%S") -> datetime:
    """Parse a compact timestamp string (e.g. '20260508_132455') as local time.
    Returns a local-timezone-aware datetime.
    """
    dt = datetime.strptime(ts_str, fmt)
    return dt.replace(tzinfo=LOCAL_TZ)
