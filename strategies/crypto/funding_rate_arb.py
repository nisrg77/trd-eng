"""
strategies/crypto/funding_rate_arb.py — Delta-Neutral Funding Rate Arbitrage Strategy

Exploits positive perpetual funding rates by identifying periods where shorting the perpetual
contract while holding spot yields high annualized returns with zero net directional exposure.
"""

from __future__ import annotations
import logging
from typing import Optional, Dict, Any
import pandas as pd
from core.signal_packet import SignalPacket
from strategies.base_strategy import BaseStrategy

log = logging.getLogger(__name__)


class FundingRateArbStrategy(BaseStrategy):
    """
    Delta-Neutral Funding Rate Arbitrage opportunity identifier.
    """

    def __init__(
        self,
        strategy_id: str = "crypto_funding_arb_01",
        params: Optional[Dict[str, Any]] = None,
        is_active: bool = True
    ) -> None:
        default_params = {
            "min_funding_rate_8h": 0.0003,  # 0.03% per 8 hours (~32% APR)
            "exit_funding_rate_8h": 0.00005, # Exit when rate drops below 0.005%
        }
        if params:
            default_params.update(params)
        super().__init__(
            strategy_id=strategy_id,
            name="Funding Rate Arbitrage",
            asset_class="crypto",
            params=default_params,
            is_active=is_active
        )

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Optional[SignalPacket]:
        if not self.is_active or df.empty:
            return None

        # Check for funding_rate column in df or metadata
        funding_rate = 0.0
        if "funding_rate" in df.columns:
            funding_rate = float(df["funding_rate"].iloc[-1])
        elif "funding_rate_8h" in self.params:
            funding_rate = float(self.params["funding_rate_8h"])

        min_rate = float(self.params["min_funding_rate_8h"])

        # When funding rate is sufficiently positive, short perpetual to collect payments
        if funding_rate >= min_rate:
            apr = funding_rate * 3 * 365 * 100
            conviction = min(0.99, 0.60 + (funding_rate / min_rate) * 0.20)

            return SignalPacket(
                strategy_id=self.strategy_id,
                asset_class=self.asset_class,
                symbol=symbol,
                direction=-1.0,  # Short Perp side of Cash & Carry
                conviction=conviction,
                suggested_stop_pct=None,  # Delta-neutral hedge, no standard directional stop
                metadata={
                    "strategy": "funding_arb",
                    "opportunity": "cash_and_carry_short_perp",
                    "funding_rate_8h": funding_rate,
                    "estimated_apr_pct": apr
                }
            )

        return None
