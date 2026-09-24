"""
strategies/crypto/bollinger_reversion.py — Hardened Baseline Bollinger Mean-Reversion Strategy

Clean, pure, position-aware strategy outputting rich OrderIntent objects:
- Entry: Price dips below lower Bollinger Band with oversold RSI.
- Exit: Position-aware profit-taking when price crosses above middle band or stop loss is reached.
"""

from __future__ import annotations
import logging
from typing import Optional, Dict, Any
import pandas as pd
from core.order_intent import OrderIntent, OrderLeg, OrderSide, IntentType, PositionContext
from data_pipeline.feature_standardizer import compute_standard_features

log = logging.getLogger(__name__)


class BollingerReversionStrategy:
    """
    Position-aware Bollinger Band Mean Reversion Strategy.
    """

    def __init__(
        self,
        strategy_id: str = "crypto_bollinger_01",
        sleeve_id: str = "sleeve_mean_reversion",
        params: Optional[Dict[str, Any]] = None
    ) -> None:
        self.strategy_id = strategy_id
        self.sleeve_id = sleeve_id
        self.params = {
            "rsi_buy_threshold": 32.0,
            "stop_loss_pct": 0.04,
            "allocation_usd": 1000.0
        }
        if params:
            self.params.update(params)

    def evaluate(
        self,
        symbol: str,
        df: pd.DataFrame,
        position_context: Optional[PositionContext] = None
    ) -> Optional[OrderIntent]:
        """
        Evaluates market state and current position context.
        """
        if df.empty or len(df) < 20:
            return None

        if "bb_lower" not in df.columns or "rsi_14" not in df.columns:
            df = compute_standard_features(df)

        last_row = df.iloc[-1]
        close = float(last_row["close"])
        bb_lower = float(last_row["bb_lower"])
        bb_middle = float(last_row["bb_middle"])
        rsi = float(last_row["rsi_14"])

        # 1. Position-Aware Exit Check
        if position_context and position_context.is_open:
            # If holding a Long and price reaches or exceeds BB middle -> Take Profit Exit!
            if position_context.side == OrderSide.BUY and close >= bb_middle:
                return OrderIntent(
                    strategy_id=self.strategy_id,
                    sleeve_id=self.sleeve_id,
                    intent_type=IntentType.EXIT,
                    legs=[OrderLeg(symbol=symbol, side=OrderSide.SELL, target_size_usd=self.params["allocation_usd"])],
                    metadata={"trigger": "take_profit_bb_middle_hit", "exit_price": close}
                )
            return None  # Continue holding

        # 2. Entry Check (Only when no position is open)
        if close <= bb_lower and rsi <= float(self.params["rsi_buy_threshold"]):
            stop_price = close * (1.0 - float(self.params["stop_loss_pct"]))
            return OrderIntent(
                strategy_id=self.strategy_id,
                sleeve_id=self.sleeve_id,
                intent_type=IntentType.ENTRY,
                legs=[OrderLeg(symbol=symbol, side=OrderSide.BUY, target_size_usd=self.params["allocation_usd"])],
                stop_loss_price=stop_price,
                take_profit_price=bb_middle,
                conviction=0.85,
                metadata={"trigger": "bb_lower_dip", "rsi": rsi, "bb_lower": bb_lower}
            )

        return None
