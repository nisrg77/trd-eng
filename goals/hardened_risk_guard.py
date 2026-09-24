"""
goals/hardened_risk_guard.py — Institutional Capital Safety & Risk Guard

Enforces:
1. Hard loss cap: Evaluates TOTAL equity drawdown (Realized + Unrealized Mark-to-Market).
2. Max position size and gross portfolio exposure limits.
3. Emergency Kill Switch: Instant memory toggle halting all new entries while permitting exits.
4. Trade ceilings per asset class.
"""

from __future__ import annotations
import math
import logging
import threading
from typing import Dict, Any, Optional
from core.order_intent import OrderIntent, IntentType
from goals.goal_module import load_state, save_state, GoalState

log = logging.getLogger(__name__)


class HardenedRiskGuard:
    """
    Institutional risk engine protecting live capital with non-bypassable constraints.
    """

    def __init__(
        self,
        max_monthly_loss_usd: float = -1000.0,
        max_position_size_usd: float = 5000.0,
        max_gross_exposure_usd: float = 20000.0,
        daily_trade_limits: Optional[Dict[str, int]] = None
    ) -> None:
        self.max_monthly_loss_usd = float(max_monthly_loss_usd)
        self.max_position_size_usd = float(max_position_size_usd)
        self.max_gross_exposure_usd = float(max_gross_exposure_usd)
        self.daily_trade_limits = daily_trade_limits or {"crypto": 20, "stock": 80}
        
        self._lock = threading.RLock()
        self._kill_switch_active = False
        self._kill_switch_reason: Optional[str] = None

    # ── Emergency Kill Switch ────────────────────────────────────────────────
    def trigger_emergency_kill_switch(self, reason: str = "Manual User Kill Switch") -> None:
        """Immediately halts all entry orders and enters defensive mode."""
        with self._lock:
            self._kill_switch_active = True
            self._kill_switch_reason = reason
            log.critical("EMERGENCY KILL SWITCH ACTIVATED! Reason: %s", reason)

    def reset_kill_switch(self) -> None:
        """Resets the kill switch after manual authorization."""
        with self._lock:
            self._kill_switch_active = False
            self._kill_switch_reason = None
            log.info("Emergency kill switch reset. Normal trading authorized.")

    @property
    def is_kill_switch_active(self) -> bool:
        with self._lock:
            return self._kill_switch_active

    # ── Intent Evaluation ───────────────────────────────────────────────────
    def evaluate_intent(
        self,
        intent: OrderIntent,
        open_positions: Dict[str, Any],
        unrealized_pnl_usd: float = 0.0,
        goal_state: Optional[GoalState] = None
    ) -> tuple[bool, str, float]:
        """
        Evaluates an OrderIntent against all risk boundaries.
        
        Returns:
            (approved: bool, reason: str, approved_size_usd: float)
        """
        with self._lock:
            # 1. Kill Switch Check
            if self._kill_switch_active:
                # Exits are ALWAYS permitted to reduce risk
                if intent.intent_type in [IntentType.EXIT, IntentType.CANCEL]:
                    return True, "Exit permitted under kill switch", 0.0
                return False, f"BLOCKED: Kill switch active ({self._kill_switch_reason})", 0.0

            # 2. Exits and Cancels always pass through
            if intent.intent_type in [IntentType.EXIT, IntentType.CANCEL]:
                return True, "Exit order approved", 0.0

            state = goal_state or load_state()

            # 3. Monthly Loss Cap on Total Equity (Realized + Unrealized)
            total_realized_this_month = (
                state.crypto.realized_pnl_this_month_usd + state.stock.realized_pnl_this_month_usd
            )
            total_net_pnl = total_realized_this_month + unrealized_pnl_usd

            if total_net_pnl <= self.max_monthly_loss_usd:
                state.engine_paused = True
                save_state(state)
                reason = (
                    f"BLOCKED: Total $1000 capital finished (${total_net_pnl:.2f} <= ${self.max_monthly_loss_usd:.2f}) "
                    f"[Realized: ${total_realized_this_month:.2f}, MTM: ${unrealized_pnl_usd:.2f}] — System Stopped"
                )
                log.warning(reason)
                return False, reason, 0.0

            if state.engine_paused:
                return False, "BLOCKED: Engine stopped: Total $1000 capital finished", 0.0

            # 4. Target Asset Class & Daily Trade Limits
            first_leg = intent.legs[0]
            is_crypto = (
                "BTC" in first_leg.symbol or "ETH" in first_leg.symbol or 
                "-USD" in first_leg.symbol or "USDT" in first_leg.symbol
            )
            asset_class = "crypto" if is_crypto else "stock"
            bucket = state.crypto if is_crypto else state.stock
            limit = self.daily_trade_limits.get(asset_class, 20)

            if bucket.trades_today >= limit:
                reason = f"BLOCKED: Daily trade limit hit for {asset_class} ({bucket.trades_today}/{limit})"
                log.warning(reason)
                return False, reason, 0.0

            # 5. Position Size and Gross Exposure Limits
            intent_total_size = sum(leg.target_size_usd for leg in intent.legs)
            if intent_total_size > self.max_position_size_usd:
                reason = f"BLOCKED: Size ${intent_total_size:.2f} exceeds max position size ${self.max_position_size_usd:.2f}"
                log.warning(reason)
                return False, reason, 0.0

            current_gross_exposure = sum(
                abs(float(p.get("size", 0.0) or p.get("qty", 0.0))) * float(p.get("entry_price", 0.0) or p.get("price", 0.0))
                for p in open_positions.values()
            )

            if (current_gross_exposure + intent_total_size) > self.max_gross_exposure_usd:
                reason = (
                    f"BLOCKED: Projected gross exposure (${current_gross_exposure + intent_total_size:.2f}) "
                    f"exceeds max portfolio exposure ${self.max_gross_exposure_usd:.2f}"
                )
                log.warning(reason)
                return False, reason, 0.0

            # All checks passed!
            return True, "Risk checks passed", intent_total_size


# Institutional Singleton
hardened_risk_guard = HardenedRiskGuard()

