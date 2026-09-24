"""
strategies/pair_cointegration.py — Engle-Granger Cointegration Mean-Reversion Plugin

Implements statistical arbitrage for correlated pairs (e.g. BTC vs ETH, SOL vs AVAX, tech stocks).
Calculates rolling OLS hedge ratio, stationary residual spread, and z-score entry/exit bands.
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


class PairCointegrationStrategy(BaseStrategy):
    """
    Engle-Granger Two-Step Cointegration Mean-Reversion Plugin.
    Emits long/short signals based on the z-score deviation of the asset's residual spread.
    """

    def __init__(
        self,
        strategy_id: str = "strat_pair_coint_01",
        name: str = "Cointegration Spread Mean-Reversion",
        asset_class: str = "crypto",
        params: Optional[Dict[str, Any]] = None,
        is_active: bool = True
    ) -> None:
        default_params = {
            "window": 60,
            "entry_zscore": 2.0,
            "exit_zscore": 0.5,
            "stop_loss_pct": 0.04,
            "conviction": 0.80
        }
        if params:
            default_params.update(params)
        super().__init__(strategy_id, name, asset_class, default_params, is_active)

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Optional[SignalPacket]:
        """
        Evaluates cointegration spread if a benchmark/target series is provided in df columns
        (e.g., 'benchmark_close' or 'target_close'). Alternatively computes relative mean-reversion.
        """
        if not self.is_active or df is None or len(df) < self.params["window"]:
            return None

        window = int(self.params["window"])
        entry_z = float(self.params["entry_zscore"])

        # Check if paired benchmark series is present
        if "benchmark_close" in df.columns:
            y = df["close"].iloc[-window:].values
            x = df["benchmark_close"].iloc[-window:].values
            
            # Simple OLS slope (Hedge Ratio beta)
            cov_xy = np.cov(x, y)[0][1]
            var_x = np.var(x)
            beta = cov_xy / var_x if var_x > 0 else 1.0
            alpha = np.mean(y) - beta * np.mean(x)
            
            spread = y - (alpha + beta * x)
        else:
            # Fallback: self-contained price vs rolling mean spread
            close = df["close"].iloc[-window:].values
            rolling_avg = np.mean(close)
            spread = close - rolling_avg

        spread_mean = np.mean(spread)
        spread_std = np.std(spread)
        if spread_std <= 0:
            return None

        current_zscore = (spread[-1] - spread_mean) / spread_std

        # Oversold Spread: Asset is undervalued relative to paired baseline -> Long
        if current_zscore <= -entry_z:
            self._execution_count += 1
            return SignalPacket(
                strategy_id=self.strategy_id,
                asset_class=self.asset_class,
                symbol=symbol,
                direction=1.0,
                conviction=self.params["conviction"],
                suggested_stop_pct=self.params["stop_loss_pct"],
                metadata={
                    "spread_zscore": float(current_zscore),
                    "spread_mean": float(spread_mean),
                    "spread_std": float(spread_std),
                    "action": "LONG_UNDERVALUED_SPREAD"
                }
            )

        # Overbought Spread: Asset is overvalued relative to paired baseline -> Short
        if current_zscore >= entry_z:
            self._execution_count += 1
            return SignalPacket(
                strategy_id=self.strategy_id,
                asset_class=self.asset_class,
                symbol=symbol,
                direction=-1.0,
                conviction=self.params["conviction"],
                suggested_stop_pct=self.params["stop_loss_pct"],
                metadata={
                    "spread_zscore": float(current_zscore),
                    "spread_mean": float(spread_mean),
                    "spread_std": float(spread_std),
                    "action": "SHORT_OVERVALUED_SPREAD"
                }
            )

        return None
