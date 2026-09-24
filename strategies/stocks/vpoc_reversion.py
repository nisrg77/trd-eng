"""
strategies/stocks/vpoc_reversion.py — Value Area & VPOC Mean-Reversion Strategy

Leverages Volume Profile structural levels (VPOC, Value Area High/Low):
When price stretches beyond the Value Area boundary and momentum slows,
initiates a mean-reverting trade back towards the Volume Point of Control (VPOC).
"""

from __future__ import annotations
import logging
from typing import Optional, Dict, Any
import pandas as pd
from core.signal_packet import SignalPacket
from strategies.base_strategy import BaseStrategy
from data_pipeline.feature_standardizer import compute_standard_features

log = logging.getLogger(__name__)


class VPOCReversionStrategy(BaseStrategy):
    """
    Volume Profile / VPOC Mean Reversion Strategy.
    """

    def __init__(
        self,
        strategy_id: str = "stock_vpoc_01",
        params: Optional[Dict[str, Any]] = None,
        is_active: bool = True
    ) -> None:
        default_params = {
            "stretch_atr_mult": 1.2,
            "stop_loss_pct": 0.025,
            "min_bars": 20,
        }
        if params:
            default_params.update(params)
        super().__init__(
            strategy_id=strategy_id,
            name="VPOC Value Area Reversion",
            asset_class="stock",
            params=default_params,
            is_active=is_active
        )

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Optional[SignalPacket]:
        if not self.is_active or df.empty or len(df) < int(self.params["min_bars"]):
            return None

        if "atr_14" not in df.columns or "vwap" not in df.columns:
            df = compute_standard_features(df)

        last_row = df.iloc[-1]
        close = float(last_row["close"])
        atr = float(last_row["atr_14"])
        vwap = float(last_row["vwap"])
        
        # Approximate Value Area from VWAP and ATR if raw VAP levels are not directly in df
        vpoc = float(last_row.get("vpoc", vwap))
        vah = float(last_row.get("vah", vpoc + 1.2 * atr))
        val = float(last_row.get("val", vpoc - 1.2 * atr))

        stretch_mult = float(self.params["stretch_atr_mult"])
        stop_pct = float(self.params["stop_loss_pct"])

        # 1. Price stretched above VAH -> Mean Revert Short back to VPOC
        if close > (vah + (stretch_mult * atr * 0.3)):
            conviction = 0.70
            return SignalPacket(
                strategy_id=self.strategy_id,
                asset_class=self.asset_class,
                symbol=symbol,
                direction=-1.0,  # Short mean reversion
                conviction=conviction,
                suggested_stop_pct=stop_pct,
                metadata={
                    "strategy": "vpoc_reversion",
                    "trigger": "vah_overextension",
                    "vpoc_target": vpoc,
                    "vah": vah,
                    "val": val
                }
            )

        # 2. Price stretched below VAL -> Mean Revert Long back to VPOC
        elif close < (val - (stretch_mult * atr * 0.3)):
            conviction = 0.70
            return SignalPacket(
                strategy_id=self.strategy_id,
                asset_class=self.asset_class,
                symbol=symbol,
                direction=1.0,  # Long mean reversion
                conviction=conviction,
                suggested_stop_pct=stop_pct,
                metadata={
                    "strategy": "vpoc_reversion",
                    "trigger": "val_underextension",
                    "vpoc_target": vpoc,
                    "vah": vah,
                    "val": val
                }
            )

        return None
