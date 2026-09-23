"""
tests/test_future_proofing_patches.py — Unit Tests for Future-Proofing Architecture Patches
"""

import unittest
import time
from collections import deque
import numpy as np
import pandas as pd

from data_pipeline.dead_day_filter import compute_dead_day_and_conviction
from goals.goal_module import position_risk_budget_usd, GoalState, evaluate_trade
from alpha_overlay.iff import check_micro_buffer_veto, _record_flow_tick
from core.symbol_state import symbol_state_registry
import config

class TestFutureProofingPatches(unittest.TestCase):
    def setUp(self):
        symbol_state_registry.clear()

    def test_dead_day_rolling_percentiles(self):
        # Generate 100 historical bars for symbol "TEST_SYM"
        dates = pd.date_range("2025-01-01", periods=100)
        df = pd.DataFrame({
            "Close": np.linspace(100, 110, 100),
            "High": np.linspace(101, 111, 100),
            "Low": np.linspace(99, 109, 100),
            "Volume": [1000.0] * 100
        }, index=dates)

        # Call filter 65 times to surpass the 60-bar cold start threshold
        for _ in range(65):
            res = compute_dead_day_and_conviction(df, ml_confidence=0.80, symbol="TEST_SYM")

        state = symbol_state_registry.get("TEST_SYM")
        self.assertIn("Percentile P10", res["filter_mode"])
        self.assertGreaterEqual(len(state.range_atr_history), 60)

    def test_equity_scaled_risk_budgeting(self):
        # Base equity scenario
        base_state = GoalState()
        budget_base = position_risk_budget_usd("crypto", state=base_state)
        self.assertEqual(budget_base, 10.0)  # Static risk budget default

    def test_micro_buffer_production_parameters(self):
        """Production parameters: hold_ms=50.0, dwell_ms=10.0 with timestamped ticks."""
        symbol = "BTC-USD"
        now = time.time()
        
        # Insert ticks spanning 25ms within 50ms window with opposing flow (-0.80 < -0.50 threshold)
        state = symbol_state_registry.get(symbol)
        state.record_flow_tick(now - 0.040, -0.80)
        state.record_flow_tick(now - 0.025, -0.80)
        state.record_flow_tick(now - 0.010, -0.80)  # 30ms total opposing duration > 10ms dwell

        preempted, reason = check_micro_buffer_veto(symbol, "BUY", hold_ms=50.0, dwell_ms=10.0)
        self.assertTrue(preempted)
        self.assertIn("Preempted", reason)

    def test_micro_buffer_short_spike_no_veto(self):
        """Short spike (<10ms dwell) should NOT trigger a veto."""
        symbol = "BTC-USD"
        now = time.time()

        state = symbol_state_registry.get(symbol)
        state.record_flow_tick(now - 0.040, 0.20)
        state.record_flow_tick(now - 0.025, -0.80)
        state.record_flow_tick(now - 0.021, -0.80)  # Only 4ms opposing duration < 10ms dwell
        state.record_flow_tick(now - 0.015, 0.10)

        preempted, reason = check_micro_buffer_veto(symbol, "BUY", hold_ms=50.0, dwell_ms=10.0)
        self.assertFalse(preempted)
        self.assertIn("Passed", reason)

    def test_micro_buffer_sanity_check(self):
        """Sanity check test for immediate preemption."""
        symbol = "ETH-USD"
        for i in range(5):
            _record_flow_tick(symbol, 0.80)  # Bullish flow

        preempted, reason = check_micro_buffer_veto(symbol, "SELL", hold_ms=5000.0, dwell_ms=0.0)
        self.assertTrue(preempted)
        self.assertIn("Preempted", reason)

if __name__ == "__main__":
    unittest.main()
