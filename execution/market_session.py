"""
execution/market_session.py — Asset-Class Trading Session & Market Hours Manager

Market Session Rules:
1. Crypto Perpetuals (BTC-USD, ETH-USD, etc.):
   - Trades 24/7/365 without market session restrictions.
2. US Equities / Stock Futures (AAPL, SPY, NVDA, CME SSF Proxies, etc.):
   - Regular Trading Hours (RTH): Monday through Friday, 09:30 - 16:00 US Eastern Time (ET / America/New_York).
   - Weekend Gaps: Saturday and Sunday are CLOSED.
   - Off-Hours: 16:00 to 09:30 ET are CLOSED for new entries.
"""

from __future__ import annotations
import os
import sys
from datetime import datetime, time as dtime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

US_EASTERN_TZ = ZoneInfo("America/New_York")


def is_crypto_symbol(symbol: str) -> bool:
    """Returns True if the symbol belongs to the Crypto asset class (24/7 trading)."""
    if not symbol:
        return False
    clean = symbol.upper()
    crypto_list = [s.upper() for s in getattr(config, "CRYPTO_INSTRUMENTS", ["BTC-USD", "ETH-USD"])]
    if clean in crypto_list:
        return True
    if clean.endswith("-USD") or clean.endswith("USDT") or "BTC" in clean or "ETH" in clean or "SOL" in clean:
        return True
    return False


def get_current_ny_time() -> datetime:
    """Returns the current datetime in US Eastern Time (America/New_York)."""
    return datetime.now(US_EASTERN_TZ)


def is_market_session_open(symbol: str, override_time: datetime | None = None) -> tuple[bool, str, dict]:
    """
    Evaluates whether the trading session is currently open for the given instrument.

    Returns:
        (is_open: bool, status_reason: str, session_info: dict)
    """
    now_ny = override_time or get_current_ny_time()
    ny_time_str = now_ny.strftime("%a %H:%M:%S %Z")
    date_str = now_ny.strftime("%Y-%m-%d")

    # 1. Crypto is always open (24/7/365)
    if is_crypto_symbol(symbol):
        return True, "Crypto 24/7 Market Active", {
            "symbol": symbol,
            "asset_class": "crypto",
            "is_open": True,
            "session_name": "24/7",
            "timezone": "UTC",
            "rth_hours": "24/7/365",
            "ny_time": ny_time_str,
            "date": date_str,
        }

    # 2. US Equities / Futures: Check config bypass flag
    enforce_hours = getattr(config, "ENFORCE_US_MARKET_HOURS", True)
    if not enforce_hours:
        return True, "US Market Hours Check Bypassed (Config Override)", {
            "symbol": symbol,
            "asset_class": "futures",
            "is_open": True,
            "session_name": "BYPASS_OVERRIDE",
            "timezone": "America/New_York",
            "rth_hours": "09:30 - 16:00 ET",
            "ny_time": ny_time_str,
            "date": date_str,
        }

    weekday = now_ny.weekday()  # 0 = Monday, ..., 4 = Friday, 5 = Saturday, 6 = Sunday
    current_t = now_ny.time()

    # RTH Window: 09:30:00 - 16:00:00 US Eastern
    rth_start = dtime(9, 30, 0)
    rth_end = dtime(16, 0, 0)

    # Check Weekend
    if weekday >= 5:
        reason = f"US Market Closed for Weekend (Current NY Time: {ny_time_str}, RTH: Mon-Fri 09:30-16:00 ET)"
        return False, reason, {
            "symbol": symbol,
            "asset_class": "futures",
            "is_open": False,
            "session_name": "CLOSED_WEEKEND",
            "timezone": "America/New_York",
            "rth_hours": "Mon-Fri 09:30 - 16:00 ET",
            "ny_time": ny_time_str,
            "date": date_str,
        }

    # Check Weekday RTH hours
    if rth_start <= current_t <= rth_end:
        reason = f"US Market Open (RTH Active: 09:30-16:00 ET, Current: {ny_time_str})"
        return True, reason, {
            "symbol": symbol,
            "asset_class": "futures",
            "is_open": True,
            "session_name": "RTH_OPEN",
            "timezone": "America/New_York",
            "rth_hours": "Mon-Fri 09:30 - 16:00 ET",
            "ny_time": ny_time_str,
            "date": date_str,
        }
    else:
        reason = f"US Market Closed (Outside RTH: 09:30-16:00 ET, Current NY Time: {ny_time_str})"
        return False, reason, {
            "symbol": symbol,
            "asset_class": "futures",
            "is_open": False,
            "session_name": "CLOSED_OFF_HOURS",
            "timezone": "America/New_York",
            "rth_hours": "Mon-Fri 09:30 - 16:00 ET",
            "ny_time": ny_time_str,
            "date": date_str,
        }


def get_market_sessions_summary() -> dict:
    """Returns a summary of both US and Crypto market sessions."""
    us_open, us_reason, us_info = is_market_session_open("SPY")
    crypto_open, crypto_reason, crypto_info = is_market_session_open("BTC-USD")
    return {
        "us": us_info,
        "crypto": crypto_info,
        "server_time_utc": datetime.utcnow().isoformat() + "Z",
        "ny_time": get_current_ny_time().strftime("%Y-%m-%d %H:%M:%S %Z"),
    }
