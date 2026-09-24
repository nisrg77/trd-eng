"""
strategies/sleeve_manager.py — Independent Capital Sleeves & Multi-Leg Hub

Solves the signal cancellation flaw:
- Breaks portfolio into isolated capital sleeves (e.g., Trend, Mean-Reversion, Delta-Neutral Arb).
- Ensures opposing signals across sleeves do not cancel to zero.
- Enforces strict capital allocation and max loss limits per sleeve.
- Routes multi-leg spread intents (e.g. Spot-Perp Funding Rate Arb) atomically.
- Supplies position context to strategies for position-aware sizing and exits.
"""

from __future__ import annotations
import time
import logging
import threading
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from core.order_intent import OrderIntent, OrderSide, IntentType, PositionContext

log = logging.getLogger(__name__)


@dataclass
class CapitalSleeve:
    """
    Isolated capital pool dedicated to a specific trading style or strategy.
    """
    sleeve_id: str
    allocated_capital_usd: float
    utilized_capital_usd: float = 0.0
    realized_pnl_usd: float = 0.0
    max_loss_limit_usd: float = -1000.0  # Sleeve circuit breaker
    regime_mode: str = "ALL"              # "ALL", "TRENDING", "RANGING", "ARBITRAGE"
    is_enabled: bool = True
    positions: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @property
    def available_capital_usd(self) -> float:
        return max(0.0, self.allocated_capital_usd - self.utilized_capital_usd)


class SleeveManager:
    """
    Coordinates independent capital sleeves, tracks isolated positions,
    and prevents opposing strategy signals from canceling each other out.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sleeves: Dict[str, CapitalSleeve] = {}
        self._symbol_regimes: Dict[str, str] = {}

    def register_sleeve(self, sleeve: CapitalSleeve) -> None:
        with self._lock:
            self._sleeves[sleeve.sleeve_id] = sleeve
            log.info(
                "[SleeveManager] Registered sleeve '%s': Allocated $%.2f, Regime=%s",
                sleeve.sleeve_id, sleeve.allocated_capital_usd, sleeve.regime_mode
            )

    def get_sleeve(self, sleeve_id: str) -> Optional[CapitalSleeve]:
        with self._lock:
            return self._sleeves.get(sleeve_id)

    def set_symbol_regime(self, symbol: str, regime: str) -> None:
        """Sets current market regime for a symbol (e.g. 'TRENDING', 'RANGING')."""
        with self._lock:
            self._symbol_regimes[symbol] = regime.upper()

    def get_symbol_regime(self, symbol: str) -> str:
        with self._lock:
            return self._symbol_regimes.get(symbol, "ALL")

    # ── Position Context Provider ────────────────────────────────────────────
    def get_position_context(
        self,
        sleeve_id: str,
        symbol: str,
        current_mark_price: float
    ) -> PositionContext:
        """
        Retrieves sleeve-specific position context for a strategy.
        """
        with self._lock:
            sleeve = self._sleeves.get(sleeve_id)
            if not sleeve or symbol not in sleeve.positions:
                return PositionContext(
                    symbol=symbol,
                    qty=0.0,
                    entry_price=0.0,
                    mark_price=current_mark_price,
                    unrealized_pnl=0.0,
                    opened_at_epoch=0.0
                )

            pos = sleeve.positions[symbol]
            qty = float(pos.get("qty", 0.0))
            entry_px = float(pos.get("entry_price", 0.0))
            opened_at = float(pos.get("opened_at", time.time()))
            unrealized = qty * (current_mark_price - entry_px)

            return PositionContext(
                symbol=symbol,
                qty=qty,
                entry_price=entry_px,
                mark_price=current_mark_price,
                unrealized_pnl=unrealized,
                opened_at_epoch=opened_at
            )

    # ── Intent Validation & Routing ──────────────────────────────────────────
    def route_intent(
        self,
        intent: OrderIntent,
        current_regime: Optional[str] = None
    ) -> tuple[bool, str]:
        """
        Validates intent against sleeve capital, regime, and circuit breakers.
        
        Returns:
            (approved: bool, reason: str)
        """
        with self._lock:
            sleeve = self._sleeves.get(intent.sleeve_id)
            if not sleeve:
                return False, f"Unknown sleeve_id: {intent.sleeve_id}"

            if not sleeve.is_enabled:
                return False, f"Sleeve '{intent.sleeve_id}' is disabled"

            # Check sleeve-specific loss floor
            if sleeve.realized_pnl_usd <= sleeve.max_loss_limit_usd:
                sleeve.is_enabled = False
                return False, (
                    f"Sleeve '{intent.sleeve_id}' breached loss floor "
                    f"(${sleeve.realized_pnl_usd:.2f} <= ${sleeve.max_loss_limit_usd:.2f})"
                )

            # Exits and cancels are always permitted
            if intent.intent_type in [IntentType.EXIT, IntentType.CANCEL]:
                return True, "Exit approved by sleeve"

            # Regime filter check
            regime = current_regime or self.get_symbol_regime(intent.legs[0].symbol)
            if sleeve.regime_mode != "ALL" and sleeve.regime_mode != regime:
                return False, (
                    f"Regime mismatch for sleeve '{intent.sleeve_id}': "
                    f"Requires {sleeve.regime_mode}, current is {regime}"
                )

            # Capital allocation check
            total_req_usd = sum(leg.target_size_usd for leg in intent.legs)
            if total_req_usd > sleeve.available_capital_usd:
                return False, (
                    f"Insufficient sleeve capital: requested ${total_req_usd:.2f}, "
                    f"available ${sleeve.available_capital_usd:.2f} (Allocated: ${sleeve.allocated_capital_usd:.2f})"
                )

            return True, "Sleeve validation passed"

    # ── Fill & Accounting Update ─────────────────────────────────────────────
    def record_fill(
        self,
        sleeve_id: str,
        symbol: str,
        side: OrderSide,
        qty: float,
        price: float,
        intent_type: IntentType
    ) -> None:
        """
        Updates sleeve internal position tracking and utilized capital after execution fill.
        """
        with self._lock:
            sleeve = self._sleeves.get(sleeve_id)
            if not sleeve:
                log.warning("[SleeveManager] Cannot record fill for unknown sleeve '%s'", sleeve_id)
                return

            pos = sleeve.positions.setdefault(symbol, {
                "qty": 0.0,
                "entry_price": 0.0,
                "opened_at": time.time()
            })

            signed_qty = qty if side == OrderSide.BUY else -qty

            if intent_type == IntentType.ENTRY:
                old_qty = pos["qty"]
                new_qty = old_qty + signed_qty
                if abs(new_qty) > 1e-7:
                    # Update weighted average entry price
                    old_cost = abs(old_qty) * pos["entry_price"]
                    add_cost = abs(signed_qty) * price
                    pos["entry_price"] = (old_cost + add_cost) / abs(new_qty)
                    pos["qty"] = new_qty
                    sleeve.utilized_capital_usd += (qty * price)
                else:
                    pos["qty"] = 0.0
                    pos["entry_price"] = 0.0

            elif intent_type == IntentType.EXIT:
                # Realize PnL
                entry_px = pos["entry_price"]
                pnl = (price - entry_px) * qty if side == OrderSide.SELL else (entry_px - price) * qty
                sleeve.realized_pnl_usd += pnl
                sleeve.utilized_capital_usd = max(0.0, sleeve.utilized_capital_usd - (qty * entry_px))
                pos["qty"] = max(0.0, pos["qty"] - qty)
                if abs(pos["qty"]) < 1e-7:
                    pos["qty"] = 0.0
                    pos["entry_price"] = 0.0
                log.info(
                    "[SleeveManager] Sleeve '%s' exited %s: Realized PnL $%.2f",
                    sleeve_id, symbol, pnl
                )

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Provides snapshot of all sleeves and their capital utilization."""
        with self._lock:
            return {
                sleeve_id: {
                    "allocated_capital_usd": s.allocated_capital_usd,
                    "utilized_capital_usd": s.utilized_capital_usd,
                    "available_capital_usd": s.available_capital_usd,
                    "realized_pnl_usd": s.realized_pnl_usd,
                    "is_enabled": s.is_enabled,
                    "regime_mode": s.regime_mode,
                    "open_positions": s.positions
                }
                for sleeve_id, s in self._sleeves.items()
            }
