"""
strategies/dual_thrust.py — Dual Thrust Opening Range Volatility Breakout Plugin

Calculates adaptive upper/lower volatility expansion thresholds using prior N-period
extremes (HH, LC, HC, LL) and multipliers (K1, K2).
Pure function: Returns SignalPacket conforming to TRDENG architecture.
"""

from __future__ import annotations
import logging
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np

from core.signal_packet import SignalPacket
from strategies.base_strategy import BaseStrategy

log = logging.getLogger(__name__)


class DualThrustStrategy(BaseStrategy):
    """
    Dual Thrust Breakout Strategy.
    Dynamically generates asymmetric upper/lower breakout lines based on historical range.
    """

    def __init__(
        self,
        strategy_id: str = "strat_dual_thrust_01",
        name: str = "Dual Thrust Volatility Breakout",
        asset_class: str = "crypto",
        params: Optional[Dict[str, Any]] = None,
        is_active: bool = True
    ) -> None:
        default_params = {
            "lookback_bars": 20,
            "k1": 0.5,           # Upper threshold multiplier
            "k2": 0.5,           # Lower threshold multiplier
            "stop_loss_pct": 0.03,
            "conviction": 0.70
        }
        if params:
            default_params.update(params)
        super().__init__(strategy_id, name, asset_class, default_params, is_active)

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Optional[SignalPacket]:
        """
        Evaluates current price vs Dual Thrust breakout thresholds.
        """
        if not self.is_active or df is None or len(df) < self.params["lookback_bars"] + 2:
            return None

        bars = int(self.params["lookback_bars"])
        k1 = float(self.params["k1"])
        k2 = float(self.params["k2"])

        # Prior N bars (excluding the current incomplete bar)
        hist = df.iloc[-bars-1:-1]
        current_bar = df.iloc[-1]

        hh = hist["high"].max()
        hc = hist["close"].max()
        lc = hist["close"].min()
        ll = hist["low"].min()

        # Dual Thrust Range formula
        range_val = max(hh - lc, hc - ll)
        if range_val <= 0:
            return None

        open_price = float(current_bar["open"])
        curr_price = float(current_bar["close"])

        buy_trigger = open_price + (k1 * range_val)
        sell_trigger = open_price - (k2 * range_val)

        # Bullish Breakout
        if curr_price > buy_trigger:
            self._execution_count += 1
            return SignalPacket(
                strategy_id=self.strategy_id,
                asset_class=self.asset_class,
                symbol=symbol,
                direction=1.0,
                conviction=self.params["conviction"],
                suggested_stop_pct=self.params["stop_loss_pct"],
                metadata={
                    "strategy_type": "DUAL_THRUST_LONG",
                    "buy_trigger": buy_trigger,
                    "sell_trigger": sell_trigger,
                    "range": range_val,
                    "open_price": open_price,
                    "current_price": curr_price
                }
            )

        # Bearish Breakdown
        if curr_price < sell_trigger:
            self._execution_count += 1
            return SignalPacket(
                strategy_id=self.strategy_id,
                asset_class=self.asset_class,
                symbol=symbol,
                direction=-1.0,
                conviction=self.params["conviction"],
                suggested_stop_pct=self.params["stop_loss_pct"],
                metadata={
                    "strategy_type": "DUAL_THRUST_SHORT",
                    "buy_trigger": buy_trigger,
                    "sell_trigger": sell_trigger,
                    "range": range_val,
                    "open_price": open_price,
                    "current_price": curr_price
                }
            )

        return None
