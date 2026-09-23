import unittest
import os
import tempfile
from datetime import date, timedelta
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
    CONFIG,
    TOTAL_CAPITAL_USD,
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

    def test_select_leverage_scaling_and_penalty(self):
        # High conviction (0.90) on normal day (range_atr_ratio = 1.0) -> high leverage
        lev_crypto = select_leverage("crypto", effective_conviction=0.90, range_atr_ratio=1.0)
        self.assertGreaterEqual(lev_crypto, 4.0)
        self.assertLessEqual(lev_crypto, 5.0)

        lev_stock = select_leverage("stock", effective_conviction=0.90, range_atr_ratio=1.0)
        self.assertGreaterEqual(lev_stock, 8.0)
        self.assertLessEqual(lev_stock, 10.0)

        # Stretched range (range_atr_ratio = 2.4) -> stretch penalty cuts leverage
        lev_stock_stretched = select_leverage("stock", effective_conviction=0.90, range_atr_ratio=2.4)
        self.assertLess(lev_stock_stretched, lev_stock)

        # Zero conviction -> MIN_LEVERAGE (1.0)
        lev_zero = select_leverage("stock", effective_conviction=0.0, range_atr_ratio=1.0)
        self.assertEqual(lev_zero, 1.0)

    def test_evaluate_trade_allowed(self):
        signal = {
            "is_dead_day": False,
            "effective_conviction": 0.75,
            "range_atr_ratio": 1.0,
        }
        dec = evaluate_trade("crypto", signal, state=self.state, persist=False)
        self.assertTrue(dec.allowed)
        self.assertGreater(dec.leverage, 1.0)
        self.assertGreater(dec.risk_budget_usd, 0.0)

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
        # Simulate crypto bucket having reached its 20 trades ceiling
        self.state.crypto.trades_this_month = 20
        signal = {
            "is_dead_day": False,
            "effective_conviction": 0.80,
            "range_atr_ratio": 1.0,
        }
        dec = evaluate_trade("crypto", signal, state=self.state, persist=False)
        self.assertFalse(dec.allowed)
        self.assertIn("monthly trade ceiling reached", dec.reason)

    def test_evaluate_trade_daily_loss_circuit_breaker(self):
        # 4% daily loss on $1000 = $40 loss
        self.state.stock.realized_pnl_today_usd = -45.0
        signal = {
            "is_dead_day": False,
            "effective_conviction": 0.80,
            "range_atr_ratio": 1.0,
        }
        dec = evaluate_trade("stock", signal, state=self.state, persist=False)
        self.assertFalse(dec.allowed)
        self.assertIn("daily loss circuit breaker hit", dec.reason)

    def test_evaluate_trade_monthly_drawdown_pause(self):
        # 18% drawdown from peak
        self.state.equity_peak_usd = 1000.0
        self.state.equity_current_usd = 800.0 # 20% drawdown
        signal = {
            "is_dead_day": False,
            "effective_conviction": 0.80,
            "range_atr_ratio": 1.0,
        }
        dec = evaluate_trade("stock", signal, state=self.state, persist=False)
        self.assertFalse(dec.allowed)
        self.assertIn("drawdown", dec.reason)
        self.assertTrue(self.state.engine_paused)

    def test_record_trade_result(self):
        record_trade_result("crypto", pnl_usd=25.0, state=self.state, persist=False)
        self.assertEqual(self.state.crypto.trades_this_month, 1)
        self.assertEqual(self.state.crypto.wins, 1)
        self.assertEqual(self.state.crypto.realized_pnl_today_usd, 25.0)
        self.assertEqual(self.state.equity_current_usd, 1025.0)
        self.assertEqual(self.state.equity_peak_usd, 1025.0)

    def test_monthly_progress_summary(self):
        record_trade_result("stock", pnl_usd=50.0, state=self.state, persist=False)
        summary = monthly_progress_summary(self.state)
        self.assertEqual(summary["monthly_target_usd"], 100.0)
        self.assertEqual(summary["monthly_pnl_usd"], 50.0)
        self.assertEqual(summary["stock_completed"], 1)
        self.assertEqual(summary["stock_ceiling"], 80)
        self.assertFalse(summary["engine_paused"])

if __name__ == "__main__":
    unittest.main()
