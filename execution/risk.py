"""
execution/risk.py — Asset-Class Separated Risk & Compliance Guard (RG)

Evaluates proposed orders against separated limits:
  1. Kelly Criterion dynamic position sizing
  2. Asset-Class Drawdown Circuit Breakers:
     - US Stock Futures: Strict 3% daily drawdown ($300 loss limit on $10,000 equity)
     - Crypto Futures: 6% daily drawdown (accommodating 24/7 intraday crypto swings)
  3. Exposure and concentration risk checks with dynamic sizing auto-trim
"""

from __future__ import annotations
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

class RiskGuard:
    def __init__(self):
        self.current_exposure_pct = 0.0
        self.exposure_by_instrument = {}
        self.daily_start_equity = 1000.0
        self.monthly_start_equity = 1000.0
        self.circuit_breaker_active = False

    def update_state(self, current_exposure: float, instrument_exposures: dict[str, dict | float], current_equity: float = 1000.0):
        """Syncs internal state with live portfolio state."""
        self.current_exposure_pct = current_exposure
        self.exposure_by_instrument = instrument_exposures

    def calculate_kelly_size(self, win_probability: float, win_loss_ratio: float = 1.5) -> float:
        """
        Kelly Criterion Formula:
            f* = (p * (b + 1) - 1) / b
        """
        p = min(max(win_probability, 0.01), 0.99)
        b = max(win_loss_ratio, 0.1)
        f_star = (p * (b + 1.0) - 1.0) / b
        half_kelly = max(0.0, f_star * 0.5)
        return min(round(half_kelly, 4), 0.20) # Cap max single allocation at 20%

    def check_order(self, proposed_order: dict, current_equity: float = 1000.0) -> dict:
        """
        Validates proposed order with asset-class specific circuit breakers.
        """
        evaluated_order = dict(proposed_order)
        evaluated_order["risk_check_timestamp"] = time.time()
        
        instrument = proposed_order.get("instrument", "BTC-USD")
        is_crypto = instrument in ["BTC-USD", "ETH-USD"]

        # Asset-Class Specific Circuit Breakers
        # US Stock Futures: Strict 3% Daily Drawdown
        # Crypto Futures: 6% Daily Drawdown
        daily_dd_limit = 0.06 if is_crypto else 0.03
        daily_dd = (self.daily_start_equity - current_equity) / max(1.0, self.daily_start_equity)
        monthly_dd = (self.monthly_start_equity - current_equity) / max(1.0, self.monthly_start_equity)

        # 1. Circuit Breaker Check
        if daily_dd >= daily_dd_limit or monthly_dd >= 0.10:
            evaluated_order["risk_state"] = "REJECTED"
            evaluated_order["failed_check"] = "circuit_breaker_active"
            asset_label = "Crypto Futures (6%)" if is_crypto else "US Stock Futures (3% / $300)"
            evaluated_order["detail"] = f"EMERGENCY: Hard circuit breaker triggered for {asset_label}."
            return evaluated_order

        # 2. Take Profit bypasses risk checks
        if proposed_order.get("is_take_profit"):
            evaluated_order["risk_state"] = "APPROVED"
            evaluated_order["checks_passed"] = ["take_profit_auto_approve"]
            return evaluated_order

        confidence = proposed_order.get("confidence", 0.5)
        action = proposed_order.get("action")
        
        # Dynamic Kelly Allocation
        kelly_alloc = self.calculate_kelly_size(confidence)
        alloc_pct = proposed_order.get("portfolio_allocation_pct", kelly_alloc)
        evaluated_order["kelly_allocation_pct"] = kelly_alloc

        prof_name = config.ACTIVE_RISK_PROFILE
        profile = config.RISK_PROFILES.get(prof_name, config.RISK_PROFILES["Balanced"])

        instr_data = self.exposure_by_instrument.get(instrument, {})
        current_instr_exposure = instr_data.get("exposure_pct", 0.0) if isinstance(instr_data, dict) else (instr_data or 0.0)
        
        # Exposure reduction always APPROVED
        if current_instr_exposure > 0 and action == "SELL":
            evaluated_order["risk_state"] = "APPROVED"
            evaluated_order["checks_passed"] = ["reducing_exposure_auto_approve"]
            evaluated_order["portfolio_allocation_pct"] = alloc_pct
            return evaluated_order

        # Auto-trim allocation if it exceeds remaining capacity
        max_allowed_by_global = max(0.0, profile["MAX_EXPOSURE_PCT"] - self.current_exposure_pct)
        max_allowed_by_instr = max(0.0, profile["CONCENTRATION_LIMIT_PCT"] - current_instr_exposure)
        
        allowed_alloc = min(alloc_pct, max_allowed_by_global, max_allowed_by_instr)

        if allowed_alloc < 0.02:
            evaluated_order["risk_state"] = "REJECTED"
            evaluated_order["failed_check"] = "exposure_limit"
            evaluated_order["detail"] = f"Remaining exposure room ({allowed_alloc:.2%}) < 2.0% minimum threshold."
        else:
            evaluated_order["risk_state"] = "APPROVED"
            evaluated_order["checks_passed"] = ["exposure_ok", "concentration_ok"]
            evaluated_order["portfolio_allocation_pct"] = round(allowed_alloc, 4)

        return evaluated_order
