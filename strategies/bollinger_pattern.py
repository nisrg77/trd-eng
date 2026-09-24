"""
strategies/bollinger_pattern.py — Double Bottom (W) & Top (M) Bollinger Pattern Plugin

Algorithmic 5-node geometric pivot recognition (L, K, J, M, I) using rolling 
standard deviations and band penetration to detect structural market turns.
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


class BollingerPatternStrategy(BaseStrategy):
    """
    Bollinger Bands Double-Bottom (W) and Double-Top (M) Pattern Recognition Strategy.
    Detects structural price pivots that pierce and test Bollinger Bands.
    """

    def __init__(
        self,
        strategy_id: str = "strat_bb_pattern_01",
        name: str = "Bollinger Pattern Recognition (W/M)",
        asset_class: str = "crypto",
        params: Optional[Dict[str, Any]] = None,
        is_active: bool = True
    ) -> None:
        default_params = {
            "window": 20,
            "num_std": 2.0,
            "lookback_period": 40,
            "alpha_threshold": 0.001,
            "stop_loss_pct": 0.035,
            "conviction": 0.75
        }
        if params:
            default_params.update(params)
        super().__init__(strategy_id, name, asset_class, default_params, is_active)

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Optional[SignalPacket]:
        """
        Scans OHLCV history for W-bottom (Bullish) or M-top (Bearish) pattern formations.
        """
        if not self.is_active or df is None or len(df) < self.params["window"] + 15:
            return None

        window = int(self.params["window"])
        num_std = float(self.params["num_std"])
        lookback = min(len(df), int(self.params["lookback_period"]))
        alpha = float(self.params["alpha_threshold"])

        close = df["close"]
        rolling_mean = close.rolling(window=window).mean()
        rolling_std = close.rolling(window=window).std()
        upper_band = rolling_mean + (num_std * rolling_std)
        lower_band = rolling_mean - (num_std * rolling_std)

        recent_close = close.iloc[-lookback:].values
        recent_lower = lower_band.iloc[-lookback:].values
        recent_upper = upper_band.iloc[-lookback:].values
        recent_mid = rolling_mean.iloc[-lookback:].values

        if np.isnan(recent_lower).any() or np.isnan(recent_upper).any():
            return None

        # Check for W-Bottom (Bullish Reversal):
        # 1. First bottom (Node K): price pierced below or touched lower band.
        # 2. Middle peak (Node J): price pulled back towards middle band.
        # 3. Second bottom (Node M): price made a higher/equal low above lower band (or held support).
        # 4. Breakout (Node I): current close breaks above middle peak (Node J).
        n = len(recent_close)
        curr_price = recent_close[-1]

        # Scan for potential J (middle peak) between index 5 and n-2
        for j_idx in range(5, n - 2):
            left_segment = recent_close[:j_idx]
            right_segment = recent_close[j_idx:-1]
            
            if len(left_segment) < 3 or len(right_segment) < 2:
                continue

            k_idx = int(np.argmin(left_segment))
            k_val = left_segment[k_idx]
            k_lower = recent_lower[k_idx]

            # Condition 1: Left bottom penetrated or touched lower band
            if k_val > k_lower * (1.0 + alpha):
                continue

            j_val = recent_close[j_idx]
            # Condition 2: Middle node is above bottom K and near/above mid band
            if j_val <= k_val or j_val < recent_mid[j_idx] * 0.995:
                continue

            m_idx = j_idx + int(np.argmin(right_segment))
            m_val = recent_close[m_idx]
            m_lower = recent_lower[m_idx]

            # Condition 3: Second bottom holds higher than lower band or higher than K
            if m_val < m_lower * (1.0 - alpha) or m_val < k_val * 0.99:
                continue

            # Condition 4: Current price breaks above middle peak Node J (Confirmation)
            if curr_price >= j_val * 0.998 and curr_price > recent_mid[-1]:
                self._execution_count += 1
                return SignalPacket(
                    strategy_id=self.strategy_id,
                    asset_class=self.asset_class,
                    symbol=symbol,
                    direction=1.0,
                    conviction=self.params["conviction"],
                    suggested_stop_pct=self.params["stop_loss_pct"],
                    metadata={
                        "pattern": "W_BOTTOM",
                        "first_bottom_k": float(k_val),
                        "mid_peak_j": float(j_val),
                        "second_bottom_m": float(m_val),
                        "breakout_price": float(curr_price)
                    }
                )

        # Check for M-Top (Bearish Reversal)
        for j_idx in range(5, n - 2):
            left_segment = recent_close[:j_idx]
            right_segment = recent_close[j_idx:-1]

            if len(left_segment) < 3 or len(right_segment) < 2:
                continue

            k_idx = int(np.argmax(left_segment))
            k_val = left_segment[k_idx]
            k_upper = recent_upper[k_idx]

            # Condition 1: Left top penetrated upper band
            if k_val < k_upper * (1.0 - alpha):
                continue

            j_val = recent_close[j_idx]
            if j_val >= k_val or j_val > recent_mid[j_idx] * 1.005:
                continue

            m_idx = j_idx + int(np.argmax(right_segment))
            m_val = recent_close[m_idx]
            m_upper = recent_upper[m_idx]

            # Condition 3: Right top stays under upper band or below K
            if m_val > m_upper * (1.0 + alpha) or m_val > k_val * 1.01:
                continue

            # Condition 4: Current price breaks below middle trough Node J
            if curr_price <= j_val * 1.002 and curr_price < recent_mid[-1]:
                self._execution_count += 1
                return SignalPacket(
                    strategy_id=self.strategy_id,
                    asset_class=self.asset_class,
                    symbol=symbol,
                    direction=-1.0,
                    conviction=self.params["conviction"],
                    suggested_stop_pct=self.params["stop_loss_pct"],
                    metadata={
                        "pattern": "M_TOP",
                        "first_top_k": float(k_val),
                        "mid_trough_j": float(j_val),
                        "second_top_m": float(m_val),
                        "breakdown_price": float(curr_price)
                    }
                )

        return None
