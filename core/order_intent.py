"""
core/order_intent.py — Rich Order Intent & Position Context Schema

Replaces thin direction floats with an institutional-grade OrderIntent model:
Supports multi-leg execution (e.g. Funding Rate Arbitrage: Long Spot + Short Perp),
position-aware exits, stop/take-profit prices, and Time-To-Live (TTL) expiration.
"""

from __future__ import annotations
import time
import math
import uuid
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any


class IntentType(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    SCALE_IN = "SCALE_IN"
    SCALE_OUT = "SCALE_OUT"
    CANCEL = "CANCEL"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass(frozen=True)
class PositionContext:
    """
    Current position state passed into strategies for position-aware exits and sizing.
    """
    symbol: str
    qty: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    opened_at_epoch: float
    leverage: float = 1.0

    @property
    def is_open(self) -> bool:
        return abs(self.qty) > 1e-7

    @property
    def side(self) -> Optional[OrderSide]:
        if not self.is_open:
            return None
        return OrderSide.BUY if self.qty > 0 else OrderSide.SELL

    @property
    def holding_duration_sec(self) -> float:
        return max(0.0, time.time() - self.opened_at_epoch)


@dataclass(frozen=True)
class OrderLeg:
    """
    Individual leg of an order intent (supports multi-asset spreads and delta-neutral arbs).
    """
    symbol: str
    side: OrderSide
    target_size_usd: float
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[float] = None
    venue: Optional[str] = None  # e.g., 'BINANCE_PERP', 'BINANCE_SPOT'

    def is_valid(self) -> bool:
        if not self.symbol or not isinstance(self.symbol, str):
            return False
        if not math.isfinite(self.target_size_usd) or self.target_size_usd <= 0:
            return False
        if self.order_type == OrderType.LIMIT:
            if self.limit_price is None or not math.isfinite(self.limit_price) or self.limit_price <= 0:
                return False
        return True


@dataclass(frozen=True)
class OrderIntent:
    """
    Rich, validated trade intent emitted by a strategy sleeve.
    """
    strategy_id: str
    sleeve_id: str
    intent_type: IntentType
    legs: List[OrderLeg]
    intent_id: str = field(default_factory=lambda: f"int_{uuid.uuid4().hex[:8]}")
    created_at: float = field(default_factory=time.time)
    time_to_live_sec: float = 30.0  # Signal expires after TTL
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    conviction: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_multi_leg(self) -> bool:
        return len(self.legs) > 1

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.time_to_live_sec

    def validate(self) -> tuple[bool, str]:
        """
        Validates mathematical finiteness, bounds, and leg definitions.
        Returns (is_valid: bool, reason: str).
        """
        if not self.strategy_id:
            return False, "Missing strategy_id"
        if not self.legs or len(self.legs) == 0:
            return False, "OrderIntent must contain at least one leg"
        if not math.isfinite(self.conviction) or not (0.0 <= self.conviction <= 1.0):
            return False, f"Invalid conviction: {self.conviction}"

        for idx, leg in enumerate(self.legs):
            if not leg.is_valid():
                return False, f"Leg [{idx}] invalid: {leg}"

        if self.stop_loss_price is not None:
            if not math.isfinite(self.stop_loss_price) or self.stop_loss_price <= 0:
                return False, f"Invalid stop_loss_price: {self.stop_loss_price}"

        if self.take_profit_price is not None:
            if not math.isfinite(self.take_profit_price) or self.take_profit_price <= 0:
                return False, f"Invalid take_profit_price: {self.take_profit_price}"

        return True, "Valid"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "strategy_id": self.strategy_id,
            "sleeve_id": self.sleeve_id,
            "intent_type": self.intent_type.value,
            "created_at": self.created_at,
            "time_to_live_sec": self.time_to_live_sec,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "conviction": self.conviction,
            "legs": [
                {
                    "symbol": leg.symbol,
                    "side": leg.side.value,
                    "target_size_usd": leg.target_size_usd,
                    "order_type": leg.order_type.value,
                    "limit_price": leg.limit_price,
                    "venue": leg.venue
                }
                for leg in self.legs
            ],
            "metadata": self.metadata
        }
