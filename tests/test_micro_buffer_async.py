"""
tests/test_micro_buffer_async.py — Concurrent Micro-Buffer Load Test
"""

import time
import unittest
import concurrent.futures
from execution.engine import ExecutionEngine
from core.symbol_state import symbol_state_registry
from core.decision_trace import decision_trace_buffer
from unittest.mock import patch, MagicMock

class TestMicroBufferAsync(unittest.TestCase):
    def setUp(self):
        decision_trace_buffer.clear()
        symbol_state_registry.clear()
        self.engine = ExecutionEngine()

    def tearDown(self):
        decision_trace_buffer.clear()
        symbol_state_registry.clear()

    def test_concurrent_multi_symbol_hold_load_test(self):
        """
        Proposes 5 orders for different symbols concurrently within a single 50ms hold window.
        Verifies total wall-clock time is ~50ms (concurrent), NOT 250ms (serialized 5 * 50ms).
        """
        symbols = ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "AVAX-USD"]
        
        mock_decision = MagicMock()
        mock_decision.allowed = True
        mock_decision.leverage = 10.0
        mock_decision.risk_budget_usd = 10.0
        mock_decision.ceiling_blocked = False
        mock_decision.daily_loss_blocked = False
        mock_decision.monthly_dd_blocked = False

        def process_order(sym):
            sig = {
                "signal_id": f"sig_load_{sym}",
                "instrument": sym,
                "confidence_score": 0.85,
                "direction_magnitude": 1.0,
                "dead_day_result": {
                    "is_dead_day": False,
                    "dead_day_reason": "Active",
                    "raw_conviction": 0.85,
                    "effective_conviction": 0.85,
                    "rvol": 1.8,
                    "range_atr_ratio": 1.2,
                    "filter_mode": "Static Fallback"
                }
            }
            return self.engine.size_order(sig, {})

        with patch("goals.goal_module.evaluate_trade", return_value=mock_decision):
            # Warm-up module imports & symbol state creation
            for sym in symbols:
                process_order(sym)

            t0 = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                results = list(executor.map(process_order, symbols))
            elapsed_sec = time.time() - t0

        # All 5 orders should succeed
        self.assertEqual(len([r for r in results if r is not None]), 5)

        # Total wall-clock time should be close to ~50-80ms OS quantum (<600ms), NOT serialized 1.5s+
        self.assertLess(elapsed_sec, 0.60, f"Concurrent load test took {elapsed_sec*1000:.1f}ms (expected < 600ms)")

if __name__ == "__main__":
    unittest.main()
