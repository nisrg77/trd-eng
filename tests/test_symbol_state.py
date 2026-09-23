"""
tests/test_symbol_state.py — Unit Tests for Consolidated SymbolState & SymbolStateRegistry
"""

import time
import unittest
import threading
from core.symbol_state import SymbolState, SymbolStateRegistry, symbol_state_registry

class TestSymbolState(unittest.TestCase):
    def setUp(self):
        symbol_state_registry.clear()

    def tearDown(self):
        symbol_state_registry.clear()

    def test_registry_isolation(self):
        s1 = symbol_state_registry.get("NVDA")
        s2 = symbol_state_registry.get("AAPL")

        s1.add_range_atr(1.5)
        s2.add_range_atr(0.8)

        self.assertEqual(len(s1.range_atr_history), 1)
        self.assertEqual(len(s2.range_atr_history), 1)
        self.assertEqual(s1.range_atr_history[0], 1.5)
        self.assertEqual(s2.range_atr_history[0], 0.8)

    def test_percentile_calculation_floor(self):
        state = symbol_state_registry.get("TSLA")
        # Cold start: less than 30 observations should return (None, None)
        p_range, p_rvol = state.get_percentile_thresholds()
        self.assertIsNone(p_range)
        self.assertIsNone(p_rvol)

        # Add 35 data points
        for i in range(1, 36):
            state.add_range_atr(float(i))
            state.add_rvol(float(i) * 0.1)

        p_range, p_rvol = state.get_percentile_thresholds(percentile_p10=10.0)
        self.assertIsNotNone(p_range)
        self.assertIsNotNone(p_rvol)
        self.assertAlmostEqual(p_range, 4.4, delta=0.5)

    def test_flow_ticks_window_filter(self):
        state = symbol_state_registry.get("SPY")
        now = time.time()
        
        state.record_flow_tick(now - 10.0, 0.2)
        state.record_flow_tick(now - 2.0, -0.6)
        state.record_flow_tick(now - 0.05, -0.8)

        recent = state.get_recent_flow_ticks(window_seconds=1.0)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0][1], -0.8)

    def test_thread_safety_concurrent_updates(self):
        state = symbol_state_registry.get("AMZN")
        threads = []

        def worker(start_val):
            for idx in range(100):
                state.add_range_atr(start_val + idx)
                state.record_flow_tick(time.time(), 0.5)

        for t_idx in range(5):
            t = threading.Thread(target=worker, args=(t_idx * 1000,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(state.range_atr_history), 252) # Maxlen cap
        self.assertEqual(len(state.flow_ticks), 500) # Maxlen cap

if __name__ == "__main__":
    unittest.main()
