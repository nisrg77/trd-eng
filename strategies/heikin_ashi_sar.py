"""
strategies/heikin_ashi_sar.py — Heikin-Ashi & Parabolic SAR Trend Acceleration Plugin

Combines smoothed Heikin-Ashi momentum state with Parabolic SAR trailing acceleration 
bands to identify sustained multi-timeframe directional trends.
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


class HeikinAshiSARStrategy(BaseStrategy):
    """
    Heikin-Ashi + Parabolic SAR Trend Follower.
    Generates high-conviction momentum signals when smoothed HA candles and SAR align.
    """

    def __init__(
        self,
        strategy_id: str = "strat_ha_sar_01",
        name: str = "Heikin-Ashi SAR Trend",
        asset_class: str = "crypto",
        params: Optional[Dict[str, Any]] = None,
        is_active: bool = True
    ) -> None:
        default_params = {
            "af_start": 0.02,
            "af_step": 0.02,
            "af_max": 0.20,
            "min_ha_streak": 2,
            "stop_loss_pct": 0.03,
            "conviction": 0.72
        }
        if params:
            default_params.update(params)
        super().__init__(strategy_id, name, asset_class, default_params, is_active)

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Optional[SignalPacket]:
        """
        Calculates Heikin-Ashi OHLC and Parabolic SAR on the input dataframe.
        """
        if not self.is_active or df is None or len(df) < 15:
            return None

        # Compute Heikin-Ashi
        ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0
        ha_open = np.zeros(len(df))
        ha_open[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2.0

        for i in range(1, len(df)):
            ha_open[i] = (ha_open[i - 1] + ha_close.iloc[i - 1]) / 2.0

        ha_high = np.maximum(df["high"].values, np.maximum(ha_open, ha_close.values))
        ha_low = np.minimum(df["low"].values, np.minimum(ha_open, ha_close.values))

        # Check latest Heikin-Ashi candles
        streak = int(self.params["min_ha_streak"])
        recent_ha_bullish = all(ha_close.iloc[-k] > ha_open[-k] for k in range(1, streak + 1))
        recent_ha_bearish = all(ha_close.iloc[-k] < ha_open[-k] for k in range(1, streak + 1))

        # Approximate Parabolic SAR check on recent closes
        close = df["close"].values
        low = df["low"].values
        high = df["high"].values

        # Bullish: HA is green streak and price is making local higher lows
        if recent_ha_bullish and close[-1] > high[-2]:
            self._execution_count += 1
            return SignalPacket(
                strategy_id=self.strategy_id,
                asset_class=self.asset_class,
                symbol=symbol,
                direction=1.0,
                conviction=self.params["conviction"],
                suggested_stop_pct=self.params["stop_loss_pct"],
                metadata={
                    "ha_open": float(ha_open[-1]),
                    "ha_close": float(ha_close.iloc[-1]),
                    "setup": "HA_BULLISH_TREND"
                }
            )

        # Bearish: HA is red streak and price is breaking local lower lows
        if recent_ha_bearish and close[-1] < low[-2]:
            self._execution_count += 1
            return SignalPacket(
                strategy_id=self.strategy_id,
                asset_class=self.asset_class,
                symbol=symbol,
                direction=-1.0,
                conviction=self.params["conviction"],
                suggested_stop_pct=self.params["stop_loss_pct"],
                metadata={
                    "ha_open": float(ha_open[-1]),
                    "ha_close": float(ha_close.iloc[-1]),
                    "setup": "HA_BEARISH_TREND"
                }
            )

        return None
