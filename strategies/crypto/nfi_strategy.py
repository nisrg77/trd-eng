"""
strategies/crypto/nfi_strategy.py — NostalgiaForInfinity (NFI) Multi-Trend Momentum Strategy

Port of the benchmark open-source crypto strategy:
Combines multi-indicator trend verification (EMA ribbon, Supertrend), volatility expansion,
and dynamic trailing exit logic.
"""

from __future__ import annotations
import logging
from typing import Optional, Dict, Any
import pandas as pd
from core.signal_packet import SignalPacket
from strategies.base_strategy import BaseStrategy
from data_pipeline.feature_standardizer import compute_standard_features

log = logging.getLogger(__name__)


class NFIStrategy(BaseStrategy):
    """
    NostalgiaForInfinity (NFI) trend-following & momentum strategy.
    """

    def __init__(
        self,
        strategy_id: str = "crypto_nfi_01",
        params: Optional[Dict[str, Any]] = None,
        is_active: bool = True
    ) -> None:
        default_params = {
            "rsi_trend_min": 45.0,
            "rsi_trend_max": 72.0,
            "adx_min": 22.0,
            "stop_loss_pct": 0.035,
            "trailing_stop": True,
        }
        if params:
            default_params.update(params)
        super().__init__(
            strategy_id=strategy_id,
            name="NostalgiaForInfinity Momentum",
            asset_class="crypto",
            params=default_params,
            is_active=is_active
        )

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Optional[SignalPacket]:
        if not self.is_active or df.empty or len(df) < 30:
            return None

        if "supertrend" not in df.columns or "adx_14" not in df.columns:
            df = compute_standard_features(df)

        last_row = df.iloc[-1]
        close = float(last_row["close"])
        rsi = float(last_row["rsi_14"])
        macd_hist = float(last_row["macd_hist"])
        adx = float(last_row["adx_14"])
        supertrend = int(last_row["supertrend"])
        vwap = float(last_row["vwap"])

        rsi_min = float(self.params["rsi_trend_min"])
        rsi_max = float(self.params["rsi_trend_max"])
        adx_min = float(self.params["adx_min"])
        stop_pct = float(self.params["stop_loss_pct"])

        # Bullish continuation: Supertrend positive, price above VWAP, expanding MACD, healthy ADX
        is_bullish_trend = supertrend == 1 and close > vwap
        is_momentum_healthy = (rsi_min <= rsi <= rsi_max) and (macd_hist > 0)
        is_strong_trend = adx >= adx_min

        if is_bullish_trend and is_momentum_healthy and is_strong_trend:
            conviction = 0.72
            if adx > 30.0:
                conviction += 0.12
            if macd_hist > df["macd_hist"].iloc[-2]:
                conviction += 0.08
            conviction = min(0.95, conviction)

            return SignalPacket(
                strategy_id=self.strategy_id,
                asset_class=self.asset_class,
                symbol=symbol,
                direction=1.0,  # Long
                conviction=conviction,
                suggested_stop_pct=stop_pct,
                metadata={
                    "strategy": "nfi",
                    "trigger": "trend_continuation",
                    "adx": adx,
                    "rsi": rsi,
                    "supertrend": supertrend,
                    "above_vwap": True
                }
            )

        # Bearish breakdown: Supertrend negative, below VWAP, negative MACD
        is_bearish = supertrend == -1 and close < vwap and macd_hist < 0
        if is_bearish and adx >= adx_min:
            return SignalPacket(
                strategy_id=self.strategy_id,
                asset_class=self.asset_class,
                symbol=symbol,
                direction=-1.0,  # Short
                conviction=0.75,
                suggested_stop_pct=stop_pct,
                metadata={
                    "strategy": "nfi",
                    "trigger": "trend_breakdown",
                    "adx": adx,
                    "supertrend": supertrend
                }
            )

        return None
