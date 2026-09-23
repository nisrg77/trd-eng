import unittest
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from execution.market_session import is_market_session_open, is_crypto_symbol
from execution.engine import ExecutionEngine
from execution.risk import RiskGuard
import config

US_EASTERN = ZoneInfo("America/New_York")

class TestMarketSession(unittest.TestCase):
    def test_crypto_always_open(self):
        is_open, reason, info = is_market_session_open("BTC-USD")
        self.assertTrue(is_open)
        self.assertEqual(info["session_name"], "24/7")

        is_open_eth, _, info_eth = is_market_session_open("ETH-USD")
        self.assertTrue(is_open_eth)

    def test_us_weekday_rth_open(self):
        # Wednesday at 11:00 AM Eastern (during RTH)
        dt_wed_rth = datetime(2026, 9, 23, 11, 0, 0, tzinfo=US_EASTERN)
        is_open, reason, info = is_market_session_open("AAPL", override_time=dt_wed_rth)
        self.assertTrue(is_open)
        self.assertEqual(info["session_name"], "RTH_OPEN")

    def test_us_weekday_off_hours_closed(self):
        # Wednesday at 02:30 AM Eastern (off-hours)
        dt_wed_night = datetime(2026, 9, 23, 2, 30, 0, tzinfo=US_EASTERN)
        is_open, reason, info = is_market_session_open("AAPL", override_time=dt_wed_night)
        self.assertFalse(is_open)
        self.assertEqual(info["session_name"], "CLOSED_OFF_HOURS")

        # Wednesday at 18:00 Eastern (after market close)
        dt_wed_evening = datetime(2026, 9, 23, 18, 0, 0, tzinfo=US_EASTERN)
        is_open_eve, _, info_eve = is_market_session_open("SPY", override_time=dt_wed_evening)
        self.assertFalse(is_open_eve)
        self.assertEqual(info_eve["session_name"], "CLOSED_OFF_HOURS")

    def test_us_weekend_closed(self):
        # Saturday at 12:00 PM Eastern
        dt_sat = datetime(2026, 9, 26, 12, 0, 0, tzinfo=US_EASTERN)
        is_open_sat, reason_sat, info_sat = is_market_session_open("NVDA", override_time=dt_sat)
        self.assertFalse(is_open_sat)
        self.assertEqual(info_sat["session_name"], "CLOSED_WEEKEND")

        # Sunday at 14:00 Eastern
        dt_sun = datetime(2026, 9, 27, 14, 0, 0, tzinfo=US_EASTERN)
        is_open_sun, _, info_sun = is_market_session_open("AAPL", override_time=dt_sun)
        self.assertFalse(is_open_sun)
        self.assertEqual(info_sun["session_name"], "CLOSED_WEEKEND")

    def test_risk_guard_blocks_closed_market(self):
        rg = RiskGuard()
        # Ensure session enforcement is on
        config.ENFORCE_US_MARKET_HOURS = True
        
        # If current time is off-hours, AAPL order should be REJECTED with market_session_closed
        is_open, _, _ = is_market_session_open("AAPL")
        if not is_open:
            order = {"instrument": "AAPL", "portfolio_allocation_pct": 0.10, "action": "BUY"}
            res = rg.check_order(order)
            self.assertEqual(res["risk_state"], "REJECTED")
            self.assertEqual(res["failed_check"], "market_session_closed")

    def test_execution_engine_skips_closed_market(self):
        ee = ExecutionEngine()
        config.ENFORCE_US_MARKET_HOURS = True
        is_open, _, _ = is_market_session_open("AAPL")
        if not is_open:
            signal = {"direction_magnitude": 0.8, "confidence_score": 0.80, "instrument": "AAPL"}
            order = ee.size_order(signal, {})
            self.assertIsNone(order)

if __name__ == "__main__":
    unittest.main()
