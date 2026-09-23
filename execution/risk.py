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
        self.trailing_win_rate = 0.55
        self.trailing_payoff_ratio = 1.50
        self.recalibration_window = 50

    def update_state(self, current_exposure: float, instrument_exposures: dict[str, dict | float], current_equity: float = 1000.0):
        """Syncs internal state with live portfolio state."""
        self.current_exposure_pct = current_exposure
        self.exposure_by_instrument = instrument_exposures

    def recalibrate_kelly_parameters(self, trades_history: list = None) -> tuple[float, float]:
        """
        Continuously recalibrates trailing win rate (p_hat) and payoff ratio (b_hat)
        over the last W=50 trades using Laplace smoothing to avoid static over-leveraging.
        """
        if trades_history is None:
            exec_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "execution_store.json")
            if os.path.exists(exec_file):
                try:
                    with open(exec_file, "r") as f:
                        trades_history = json.load(f)
                except Exception:
                    trades_history = []
            else:
                trades_history = []

        closed_trades = [t for t in trades_history if isinstance(t, dict) and "realized_pnl" in t][-self.recalibration_window:]
        if not closed_trades:
            return self.trailing_win_rate, self.trailing_payoff_ratio

        wins = [t["realized_pnl"] for t in closed_trades if t.get("realized_pnl", 0) > 0]
        losses = [abs(t["realized_pnl"]) for t in closed_trades if t.get("realized_pnl", 0) < 0]

        # Laplace smoothing (Uniform Beta(1,1) prior)
        n_wins = len(wins)
        n_total = len(closed_trades)
        p_hat = (n_wins + 1.0) / (n_total + 2.0)

        # Dynamic Payoff Ratio
        avg_win = (sum(wins) / n_wins) if n_wins > 0 else 1.5
        avg_loss = (sum(losses) / len(losses)) if losses else 1.0
        b_hat = max(0.5, min(4.0, avg_win / max(0.01, avg_loss)))

        self.trailing_win_rate = round(p_hat, 4)
        self.trailing_payoff_ratio = round(b_hat, 4)
        return self.trailing_win_rate, self.trailing_payoff_ratio

    def calculate_kelly_size(self, win_probability: float = 0.5, win_loss_ratio: float = None) -> float:
        """
        Kelly Criterion Formula with Dynamic Trailing Recalibration:
            f* = 0.5 * [ (p * (b + 1) - 1) / b ]
        """
        if win_loss_ratio is None:
            win_loss_ratio = self.trailing_payoff_ratio

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
        existing_side = instr_data.get("side") if isinstance(instr_data, dict) else ("LONG" if current_instr_exposure > 0 else None)
        
        # Exposure reduction always APPROVED:
        # A SELL reduces exposure if the existing position is LONG.
        # A BUY reduces exposure if the existing position is SHORT.
        is_reducing = (
            (existing_side == "LONG" and action == "SELL") or
            (existing_side == "SHORT" and action == "BUY")
        )
        if is_reducing:
            evaluated_order["risk_state"] = "APPROVED"
            evaluated_order["checks_passed"] = ["reducing_exposure_auto_approve"]
            evaluated_order["portfolio_allocation_pct"] = alloc_pct
            return evaluated_order

        # Market Session Check (for new entries & exposure-increasing orders)
        from execution.market_session import is_market_session_open
        is_open, session_reason, _ = is_market_session_open(instrument)
        if not is_open:
            evaluated_order["risk_state"] = "REJECTED"
            evaluated_order["failed_check"] = "market_session_closed"
            evaluated_order["detail"] = session_reason
            return evaluated_order

        # Auto-trim allocation if it exceeds remaining capacity
        max_exposure = getattr(config, "MAX_EXPOSURE_PCT", profile.get("MAX_EXPOSURE_PCT", 0.80))
        conc_limit = getattr(config, "CONCENTRATION_LIMIT_PCT", profile.get("CONCENTRATION_LIMIT_PCT", 0.25))

        remaining_exposure = max(0.0, max_exposure - self.current_exposure_pct)
        if alloc_pct > remaining_exposure + 1e-6:
            if remaining_exposure >= 0.01:
                alloc_pct = round(remaining_exposure, 4)
                evaluated_order["auto_trimmed"] = True
                evaluated_order["trim_reason"] = "portfolio_exposure_limit"
            else:
                evaluated_order["risk_state"] = "REJECTED"
                evaluated_order["failed_check"] = "exposure_limit"
                evaluated_order["detail"] = f"Remaining exposure room ({remaining_exposure:.2%}) < requested minimum (1%)."
                return evaluated_order

        remaining_conc = max(0.0, conc_limit - current_instr_exposure)
        if alloc_pct > remaining_conc + 1e-6:
            if remaining_conc >= 0.01:
                alloc_pct = round(remaining_conc, 4)
                evaluated_order["auto_trimmed"] = True
                evaluated_order["trim_reason"] = "concentration_limit"
            else:
                evaluated_order["risk_state"] = "REJECTED"
                evaluated_order["failed_check"] = "concentration_limit"
                evaluated_order["detail"] = f"Concentration limit exceeded for {instrument} ({current_instr_exposure:.2%} > {conc_limit:.2%})."
                return evaluated_order

        evaluated_order["risk_state"] = "APPROVED"
        evaluated_order["checks_passed"] = ["exposure_ok", "concentration_ok"]
        evaluated_order["portfolio_allocation_pct"] = round(alloc_pct, 4)

        return evaluated_order
