"""
utils/time_utils.py — Central IST Time Utilities

All display timestamps, logs, and stored timestamps use IST (UTC+5:30).
API calls to Alpaca/Binance still use UTC (required by those APIs).
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta

# Indian Standard Time: UTC + 5:30
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def now_ist() -> datetime:
    """Return current datetime in IST."""
    return datetime.now(IST)


def now_ist_iso() -> str:
    """Return current IST datetime as ISO 8601 string with +05:30 offset."""
    return now_ist().isoformat()


def now_ist_str(fmt: str = "%Y-%m-%d %H:%M:%S IST") -> str:
    """Return current IST datetime as a human-readable string."""
    return now_ist().strftime(fmt)


def utc_to_ist(dt: datetime) -> datetime:
    """Convert a UTC-aware datetime to IST."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def ts_to_ist_iso(ts: float) -> str:
    """Convert a Unix timestamp (float) to IST ISO string."""
    return datetime.fromtimestamp(ts, tz=IST).isoformat()


def ts_to_ist_str(ts: float, fmt: str = "%Y-%m-%d %H:%M:%S IST") -> str:
    """Convert a Unix timestamp to human-readable IST string."""
    return datetime.fromtimestamp(ts, tz=IST).strftime(fmt)
