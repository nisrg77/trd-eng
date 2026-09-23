import unittest
import os
import tempfile
from datetime import date
from goals.goal_module import (
    evaluate_trade,
    record_trade_result,
    select_leverage,
    position_risk_budget_usd,
    monthly_progress_summary,
    GoalState,
    BucketState,
    save_state,
    load_state,
    MAX_MONTHLY_LOSS_USD,
    DAILY_TRADE_LIMITS,
    STATIC_LEVERAGE,
    STATIC_RISK_BUDGET,
)

class TestGoalModule(unittest.TestCase):
    def setUp(self):
        # Create a temporary file for state testing
        self.temp_fd, self.temp_path = tempfile.mkstemp(suffix=".json")
        os.close(self.temp_fd)
        self.state = GoalState()
        save_state(self.state, self.temp_path)

    def tearDown(self):
        if os.path.exists(self.temp_path):
            os.remove(self.temp_path)

    def test_static_leverage_and_risk_budget(self):
        lev = select_leverage("crypto", effective_conviction=0.90, range_atr_ratio=1.0)
        self.assertEqual(lev, 4.6)

        budget = position_risk_budget_usd("crypto", state=self.state)
        self.assertEqual(budget, STATIC_RISK_BUDGET)

    def test_evaluate_trade_allowed(self):
        signal = {
            "is_dead_day": False,
            "effective_conviction": 0.75,
            "range_atr_ratio": 1.0,
        }
        dec = evaluate_trade("crypto", signal, state=self.state, persist=False)
        self.assertTrue(dec.allowed)
        self.assertEqual(dec.leverage, 4.0)
        self.assertEqual(dec.risk_budget_usd, STATIC_RISK_BUDGET)

    def test_evaluate_trade_dead_day_blocked(self):
        signal = {
            "is_dead_day": True,
            "dead_day_reason": "Range/ATR: 0.45, RVOL: 0.50x",
            "effective_conviction": 0.0,
            "range_atr_ratio": 0.45,
        }
        dec = evaluate_trade("stock", signal, state=self.state, persist=False)
        self.assertFalse(dec.allowed)
        self.assertIn("Dead day", dec.reason)

    def test_evaluate_trade_ceiling_blocked(self):
        # Simulate crypto bucket having reached its 20 trades ceiling today
        self.state.crypto.trades_today = DAILY_TRADE_LIMITS["crypto"]
        signal = {
            "is_dead_day": False,
            "effective_conviction": 0.80,
            "range_atr_ratio": 1.0,
        }
        dec = evaluate_trade("crypto", signal, state=self.state, persist=False)
        self.assertFalse(dec.allowed)
        self.assertIn("daily trade limit reached", dec.reason)

    def test_evaluate_trade_monthly_loss_limit_blocked(self):
        # Breach monthly loss limit (-$1000)
        self.state.crypto.realized_pnl_this_month_usd = -600.0
        self.state.stock.realized_pnl_this_month_usd = -450.0
        signal = {
            "is_dead_day": False,
            "effective_conviction": 0.80,
            "range_atr_ratio": 1.0,
        }
        dec = evaluate_trade("stock", signal, state=self.state, persist=False)
        self.assertFalse(dec.allowed)
        self.assertIn("Monthly loss limit hit", dec.reason)
        self.assertTrue(self.state.engine_paused)

    def test_record_trade_result(self):
        record_trade_result("crypto", pnl_usd=25.0, state=self.state, persist=False)
        self.assertEqual(self.state.crypto.trades_today, 1)
        self.assertEqual(self.state.crypto.realized_pnl_this_month_usd, 25.0)

    def test_monthly_progress_summary(self):
        record_trade_result("stock", pnl_usd=50.0, state=self.state, persist=False)
        summary = monthly_progress_summary(self.state)
        self.assertEqual(summary["monthly_pnl_usd"], 50.0)
        self.assertEqual(summary["stock_completed"], 1)
        self.assertEqual(summary["stock_ceiling"], 80)
        self.assertFalse(summary["engine_paused"])

if __name__ == "__main__":
    unittest.main()
