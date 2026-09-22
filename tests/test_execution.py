import unittest
from execution.engine import ExecutionEngine
from execution.risk import RiskGuard
import config

class TestExecutionEngine(unittest.TestCase):
    def setUp(self):
        self.ee = ExecutionEngine()
        config.MIN_CONFIDENCE_THRESHOLD = 0.35
        config.KELLY_FRACTION = 0.5
        config.MAX_POSITION_SIZE_PCT = 0.20

    def test_size_order_low_confidence(self):
        signal = {"direction_magnitude": 0.5, "confidence_score": 0.20}
        order = self.ee.size_order(signal, {})
        self.assertIsNone(order)

    def test_size_order_valid_buy(self):
        signal = {"direction_magnitude": 0.8, "confidence_score": 0.60, "instrument": "AAPL"}
        order = self.ee.size_order(signal, {})
        self.assertIsNotNone(order)
        self.assertEqual(order["action"], "BUY")
        self.assertEqual(order["instrument"], "AAPL")
        self.assertFalse(order["is_take_profit"])

    def test_size_order_valid_sell(self):
        signal = {"direction_magnitude": -0.8, "confidence_score": 0.60, "instrument": "AAPL"}
        order = self.ee.size_order(signal, {})
        self.assertIsNotNone(order)
        self.assertEqual(order["action"], "SELL")
        self.assertFalse(order["is_take_profit"])
        
    def test_take_profit_trigger(self):
        # Even with low confidence, TP should trigger
        signal = {"direction_magnitude": 0.1, "confidence_score": 0.10, "instrument": "AAPL"}
        # Simulate an existing position with a 15% gain (threshold is 10% for Balanced)
        instrument_data = {"AAPL": {"exposure_pct": 0.10, "unrealized_plpc": 0.15}}
        
        order = self.ee.size_order(signal, instrument_data)
        
        self.assertIsNotNone(order)
        self.assertTrue(order["is_take_profit"])
        self.assertEqual(order["action"], "SELL") # Because we are long
        # Balanced profile sells 50% of exposure (0.10 * 0.50 = 0.05)
        self.assertAlmostEqual(order["portfolio_allocation_pct"], 0.05)

class TestRiskGuard(unittest.TestCase):
    def setUp(self):
        self.rg = RiskGuard()
        config.MAX_EXPOSURE_PCT = 0.80
        config.CONCENTRATION_LIMIT_PCT = 0.25

    def test_check_order_pass(self):
        self.rg.update_state(0.10, {"AAPL": {"exposure_pct": 0.05}})
        order = {"instrument": "AAPL", "portfolio_allocation_pct": 0.10, "action": "BUY"}
        res = self.rg.check_order(order)
        self.assertEqual(res["risk_state"], "APPROVED")

    def test_check_order_fail_exposure(self):
        self.rg.update_state(0.75, {"AAPL": {"exposure_pct": 0.05}})
        order = {"instrument": "SPY", "portfolio_allocation_pct": 0.10, "action": "BUY"}
        res = self.rg.check_order(order)
        self.assertEqual(res["risk_state"], "REJECTED")
        self.assertEqual(res["failed_check"], "exposure_limit")

    def test_check_order_fail_concentration(self):
        self.rg.update_state(0.10, {"AAPL": {"exposure_pct": 0.20}})
        order = {"instrument": "AAPL", "portfolio_allocation_pct": 0.10, "action": "BUY"}
        res = self.rg.check_order(order)
        self.assertEqual(res["risk_state"], "REJECTED")
        self.assertEqual(res["failed_check"], "concentration_limit")
        
    def test_check_order_take_profit_bypass(self):
        # Max exposure is 80%. We are at 75%. Trying to buy 10% would fail normally.
        self.rg.update_state(0.75, {"AAPL": {"exposure_pct": 0.20}})
        # But this is a take-profit order (sell).
        order = {"instrument": "AAPL", "portfolio_allocation_pct": 0.10, "action": "SELL", "is_take_profit": True}
        res = self.rg.check_order(order)
        self.assertEqual(res["risk_state"], "APPROVED")
        self.assertIn("take_profit_auto_approve", res["checks_passed"])

if __name__ == '__main__':
    unittest.main()
