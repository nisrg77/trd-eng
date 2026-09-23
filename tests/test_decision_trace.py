"""
tests/test_decision_trace.py — Unit Tests for DecisionTrace Record Generation
"""

import unittest
import time
from core.decision_trace import DecisionTrace, decision_trace_buffer
from execution.engine import ExecutionEngine
from core.symbol_state import symbol_state_registry

class TestDecisionTrace(unittest.TestCase):
    def setUp(self):
        decision_trace_buffer.clear()
        symbol_state_registry.clear()
        self.engine = ExecutionEngine()

    def tearDown(self):
        decision_trace_buffer.clear()
        symbol_state_registry.clear()

    def test_decision_trace_fields(self):
        trace = DecisionTrace(
            symbol="NVDA",
            timestamp=time.time(),
            s_composite_raw=0.85,
            s_flow=0.20,
            iff_veto=False,
            iff_scaled_signal=0.935,
            dead_day=False,
            dead_day_filter_mode="Static Fallback",
            effective_conviction=0.85,
            leverage=10.0,
            risk_budget_usd=10.0,
            gate_ceiling_blocked=False,
            gate_daily_loss_blocked=False,
            gate_monthly_dd_blocked=False,
            micro_buffer_preempted=False,
            micro_buffer_reason="Passed",
            lob_imbalance_blocked=False,
            final_action="EXECUTED"
        )
        decision_trace_buffer.record_trace(trace)
        
        traces = decision_trace_buffer.get_recent_traces(limit=10)
        self.assertEqual(len(traces), 1)
        t = traces[0]
        self.assertEqual(t["symbol"], "NVDA")
        self.assertEqual(t["final_action"], "EXECUTED")
        self.assertFalse(t["dead_day"])

    def test_size_order_dead_day_blocked_trace(self):
        signal = {
            "signal_id": "sig_dead_1",
            "instrument": "BTC-USD",
            "confidence_score": 0.80,
            "direction_magnitude": 1.0,
            "dead_day_result": {
                "is_dead_day": True,
                "dead_day_reason": "Low range ATR",
                "raw_conviction": 0.80,
                "effective_conviction": 0.0,
                "rvol": 0.4,
                "range_atr_ratio": 0.3,
                "filter_mode": "Static Fallback"
            }
        }
        res = self.engine.size_order(signal, {})
        self.assertIsNone(res)

        traces = decision_trace_buffer.get_recent_traces(limit=10)
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["final_action"], "BLOCKED_DEAD_DAY")
        self.assertTrue(traces[0]["dead_day"])

    def test_size_order_micro_buffer_preempted_trace(self):
        from unittest.mock import patch, MagicMock
        symbol = "ETH-USD"
        now = time.time()
        
        # Pre-seed micro buffer with opposing flow spike (-0.90 < -0.50)
        state = symbol_state_registry.get(symbol)
        state.record_flow_tick(now - 0.040, -0.90)
        state.record_flow_tick(now - 0.020, -0.90)
        state.record_flow_tick(now - 0.005, -0.90)

        signal = {
            "signal_id": "sig_micro_1",
            "instrument": symbol,
            "confidence_score": 0.85,
            "direction_magnitude": 1.0, # BUY signal
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

        mock_decision = MagicMock()
        mock_decision.allowed = True
        mock_decision.leverage = 10.0
        mock_decision.risk_budget_usd = 10.0
        mock_decision.ceiling_blocked = False
        mock_decision.daily_loss_blocked = False
        mock_decision.monthly_dd_blocked = False

        with patch("goals.goal_module.evaluate_trade", return_value=mock_decision):
            res = self.engine.size_order(signal, {})
            self.assertIsNone(res)

            traces = decision_trace_buffer.get_recent_traces(limit=10)
            self.assertEqual(len(traces), 1)
            self.assertEqual(traces[0]["final_action"], "BLOCKED_MICRO_BUFFER")
            self.assertTrue(traces[0]["micro_buffer_preempted"])

if __name__ == "__main__":
    unittest.main()
