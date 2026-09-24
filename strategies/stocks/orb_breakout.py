"""
strategies/stocks/orb_breakout.py — Opening Range Breakout (ORB) Strategy

Standard institutional strategy for US Equities and Index Futures (SPY, AAPL, CME SSF):
Establishes the high and low bounds of the opening session window (default 15m/30m)
and trades high-conviction momentum continuations when price breaks out of the range.
"""

from __future__ import annotations
import logging
from typing import Optional, Dict, Any
import pandas as pd
from core.signal_packet import SignalPacket
from strategies.base_strategy import BaseStrategy
from execution.market_session import is_market_session_open

log = logging.getLogger(__name__)


class ORBBreakoutStrategy(BaseStrategy):
    """
    Opening Range Breakout (ORB) Strategy for US Equities & Futures.
    """

    def __init__(
        self,
        strategy_id: str = "stock_orb_01",
        params: Optional[Dict[str, Any]] = None,
        is_active: bool = True
    ) -> None:
        default_params = {
            "orb_bars": 3,               # e.g. 3 x 5m = 15m opening range
            "atr_target_mult": 1.5,      # Take-profit multiple of ATR
            "stop_loss_pct": 0.02,       # 2% stop limit
            "check_session_hours": True, # Gated by RTH session
        }
        if params:
            default_params.update(params)
        super().__init__(
            strategy_id=strategy_id,
            name="Opening Range Breakout (ORB)",
            asset_class="stock",
            params=default_params,
            is_active=is_active
        )

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Optional[SignalPacket]:
        if not self.is_active or df.empty:
            return None

        # 1. Market session check
        if self.params.get("check_session_hours", True):
            is_open, reason, _ = is_market_session_open(symbol)
            if not is_open:
                log.debug("[%s] Session closed for %s (%s) — no ORB signal", self.strategy_id, symbol, reason)
                return None

        orb_bars = int(self.params.get("orb_bars", 3))
        if len(df) < orb_bars + 2:
            return None

        # 2. Compute opening range from first orb_bars of the current session window
        opening_df = df.iloc[:orb_bars]
        orb_high = float(opening_df["high"].max())
        orb_low = float(opening_df["low"].min())
        orb_range = orb_high - orb_low

        if orb_range <= 0:
            return None

        last_row = df.iloc[-1]
        close = float(last_row["close"])
        volume = float(last_row["volume"])
        avg_volume = float(df["volume"].rolling(10, min_periods=1).mean().iloc[-1])

        stop_pct = float(self.params["stop_loss_pct"])

        # 3. Bullish Breakout above Opening High
        if close > orb_high:
            conviction = 0.75
            if volume > avg_volume * 1.3:
                conviction += 0.15
            conviction = min(0.95, conviction)

            return SignalPacket(
                strategy_id=self.strategy_id,
                asset_class=self.asset_class,
                symbol=symbol,
                direction=1.0,  # Long Breakout
                conviction=conviction,
                suggested_stop_pct=stop_pct,
                metadata={
                    "strategy": "orb_breakout",
                    "trigger": "orb_high_breakout",
                    "orb_high": orb_high,
                    "orb_low": orb_low,
                    "orb_range": orb_range,
                    "target_price": close + (orb_range * float(self.params["atr_target_mult"]))
                }
            )

        # 4. Bearish Breakdown below Opening Low
        elif close < orb_low:
            conviction = 0.75
            if volume > avg_volume * 1.3:
                conviction += 0.15
            conviction = min(0.95, conviction)

            return SignalPacket(
                strategy_id=self.strategy_id,
                asset_class=self.asset_class,
                symbol=symbol,
                direction=-1.0,  # Short Breakdown
                conviction=conviction,
                suggested_stop_pct=stop_pct,
                metadata={
                    "strategy": "orb_breakout",
                    "trigger": "orb_low_breakdown",
                    "orb_high": orb_high,
                    "orb_low": orb_low,
                    "orb_range": orb_range
                }
            )

        return None
