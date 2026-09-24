"""
strategies/crypto/binh_cluc.py — Combined BinH & Cluc Panic Dip-Buying Strategy

Port of the legendary Freqtrade community strategy:
Identifies panic liquidation dips below lower Bollinger Bands accompanied by volume surges
and oversold momentum, targeting rapid mean-reversion bounces.
"""

from __future__ import annotations
import logging
from typing import Optional, Dict, Any
import pandas as pd
from core.signal_packet import SignalPacket
from strategies.base_strategy import BaseStrategy
from data_pipeline.feature_standardizer import compute_standard_features

log = logging.getLogger(__name__)


class BinhClucStrategy(BaseStrategy):
    """
    Combined BinH & Cluc crypto dip-buying mean-reversion strategy.
    """

    def __init__(
        self,
        strategy_id: str = "crypto_binh_cluc_01",
        params: Optional[Dict[str, Any]] = None,
        is_active: bool = True
    ) -> None:
        default_params = {
            "rsi_buy_threshold": 32.0,
            "volume_mult": 1.4,
            "bb_std": 2.0,
            "stop_loss_pct": 0.04,
            "take_profit_rsi": 65.0,
        }
        if params:
            default_params.update(params)
        super().__init__(
            strategy_id=strategy_id,
            name="Combined BinH & Cluc Dip Buyer",
            asset_class="crypto",
            params=default_params,
            is_active=is_active
        )

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Optional[SignalPacket]:
        if not self.is_active or df.empty or len(df) < 25:
            return None

        # Ensure standard technical indicators are present
        if "bb_lower" not in df.columns or "rsi_14" not in df.columns:
            df = compute_standard_features(df)

        last_row = df.iloc[-1]
        close = float(last_row["close"])
        bb_lower = float(last_row["bb_lower"])
        bb_middle = float(last_row["bb_middle"])
        rsi = float(last_row["rsi_14"])
        volume = float(last_row["volume"])
        avg_volume = float(df["volume"].rolling(20, min_periods=1).mean().iloc[-1])

        rsi_thresh = float(self.params["rsi_buy_threshold"])
        vol_mult = float(self.params["volume_mult"])
        stop_pct = float(self.params["stop_loss_pct"])

        # Entry condition: Price pierced below lower BB, high volume panic, oversold RSI
        is_dip = close <= bb_lower
        is_vol_surge = volume >= (avg_volume * vol_mult)
        is_oversold = rsi <= rsi_thresh

        if is_dip and is_oversold:
            # Scaled conviction based on volume surge and oversold depth
            conviction = 0.70
            if is_vol_surge:
                conviction += 0.18
            if rsi < 25.0:
                conviction += 0.10
            conviction = min(0.98, conviction)

            return SignalPacket(
                strategy_id=self.strategy_id,
                asset_class=self.asset_class,
                symbol=symbol,
                direction=1.0,  # Buy / Long
                conviction=conviction,
                suggested_stop_pct=stop_pct,
                metadata={
                    "strategy": "binh_cluc",
                    "trigger": "bb_lower_dip_bounce",
                    "rsi": rsi,
                    "volume_ratio": volume / (avg_volume + 1e-9),
                    "bb_lower": bb_lower,
                    "target_exit_price": bb_middle
                }
            )

        # Exit / Short condition: Overbought rebound
        if rsi >= float(self.params["take_profit_rsi"]) and close > bb_middle:
            return SignalPacket(
                strategy_id=self.strategy_id,
                asset_class=self.asset_class,
                symbol=symbol,
                direction=-1.0,  # Close / Exit signal
                conviction=0.75,
                suggested_stop_pct=stop_pct,
                metadata={
                    "strategy": "binh_cluc",
                    "trigger": "tp_overbought_exit",
                    "rsi": rsi
                }
            )

        # Flat / Neutral
        return None
