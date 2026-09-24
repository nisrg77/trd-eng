"""
execution/cost_model.py — Unified Transaction Cost & Friction Engine

Standardized cost accounting shared across:
1. Offline RL environment (research/rl/trading_env.py)
2. Live execution / shadow evaluation (execution/fill_model.py, core/decision_trace.py)

Deterministic, config-driven, and completely free of torch/SB3/gymnasium dependencies.
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass(frozen=True)
class CostModelConfig:
    """Config-driven transaction friction parameters."""
    taker_fee_bps: float = 4.0        # 4 bps = 0.0004
    maker_fee_bps: float = 2.0        # 2 bps = 0.0002
    spread_bps: float = 2.0           # 2 bps = 0.0002 total spread (1 bp half-spread)
    slippage_atr_ratio: float = 0.05  # Slippage penalty = 5% of ATR / price


@dataclass(frozen=True)
class CostBreakdown:
    """Detailed breakdown of transaction costs for a position transition."""
    position_delta: float
    fee_rate: float
    spread_rate: float
    slippage_rate: float
    total_cost_rate: float
    total_cost_usd: float = 0.0

    @property
    def total_cost_pct(self) -> float:
        return self.total_cost_rate * 100.0


class CostModel:
    """
    Computes deterministic transaction costs given market state and position changes.
    """

    def __init__(self, config: Optional[CostModelConfig] = None) -> None:
        self.config = config or CostModelConfig()

    def calculate_cost(
        self,
        price: float,
        atr: float,
        current_pos: float,
        target_pos: float,
        is_taker: bool = True,
        notional_usd: float = 1000.0
    ) -> CostBreakdown:
        """
        Calculates transaction cost for transitioning from current_pos to target_pos.
        
        Parameters:
            price: Current bar price (fill price).
            atr: 14-period Average True Range in price units.
            current_pos: Current position in [-1.0, 1.0].
            target_pos: Target position in [-1.0, 1.0].
            is_taker: Whether order executes as a market taker (default True).
            notional_usd: Trade allocation in USD.
            
        Returns:
            CostBreakdown with unit rates and total dollar cost.
        """
        delta = abs(target_pos - current_pos)
        if delta < 1e-7 or price <= 0:
            return CostBreakdown(
                position_delta=0.0,
                fee_rate=0.0,
                spread_rate=0.0,
                slippage_rate=0.0,
                total_cost_rate=0.0,
                total_cost_usd=0.0
            )

        # 1. Exchange Fee Rate
        fee_bps = self.config.taker_fee_bps if is_taker else self.config.maker_fee_bps
        fee_rate = (fee_bps * 1e-4) * delta

        # 2. Bid-Ask Spread Rate (Half-spread crossed per trade)
        half_spread_bps = self.config.spread_bps / 2.0
        spread_rate = (half_spread_bps * 1e-4) * delta

        # 3. Slippage Rate proportional to ATR
        atr_ratio = max(0.0, atr / max(price, 1e-4))
        slippage_rate = (self.config.slippage_atr_ratio * atr_ratio) * delta

        total_rate = fee_rate + spread_rate + slippage_rate
        total_usd = notional_usd * total_rate

        return CostBreakdown(
            position_delta=delta,
            fee_rate=fee_rate,
            spread_rate=spread_rate,
            slippage_rate=slippage_rate,
            total_cost_rate=total_rate,
            total_cost_usd=round(total_usd, 4)
        )


# Global deterministic singleton
cost_model = CostModel()
