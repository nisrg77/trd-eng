"""
strategies/crypto/freqtrade_adapter.py — Standalone Freqtrade Strategy Adapter

Enables executing any Freqtrade IStrategy class as a pure strategy plugin inside TRDENG
without needing the full Freqtrade server or background daemons.
"""

from __future__ import annotations
import logging
from typing import Optional, Dict, Any, Type
import pandas as pd
from core.signal_packet import SignalPacket
from strategies.base_strategy import BaseStrategy

log = logging.getLogger(__name__)


class FreqtradeAdapter(BaseStrategy):
    """
    Wraps a Freqtrade-compatible strategy class into a TRDENG BaseStrategy.
    """

    def __init__(
        self,
        strategy_class: Optional[Type] = None,
        strategy_id: str = "freqtrade_custom_01",
        name: str = "Freqtrade Custom Strategy",
        params: Optional[Dict[str, Any]] = None,
        is_active: bool = True
    ) -> None:
        super().__init__(
            strategy_id=strategy_id,
            name=name,
            asset_class="crypto",
            params=params or {},
            is_active=is_active
        )
        self.strategy_class = strategy_class
        self._strategy_instance = None
        if strategy_class:
            try:
                self._strategy_instance = strategy_class(config=self.params)
            except Exception:
                try:
                    self._strategy_instance = strategy_class()
                except Exception as e:
                    log.warning("Could not instantiate Freqtrade class %s: %s", strategy_class, e)

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Optional[SignalPacket]:
        if not self.is_active or df.empty or self._strategy_instance is None:
            return None

        try:
            # 1. Populate indicators
            dataframe = df.copy()
            metadata = {"pair": symbol}
            
            if hasattr(self._strategy_instance, "populate_indicators"):
                dataframe = self._strategy_instance.populate_indicators(dataframe, metadata)

            # 2. Populate entry trend
            if hasattr(self._strategy_instance, "populate_entry_trend"):
                dataframe = self._strategy_instance.populate_entry_trend(dataframe, metadata)

            # 3. Read latest signals
            last_bar = dataframe.iloc[-1]
            enter_long = bool(last_bar.get("enter_long", 0))
            enter_short = bool(last_bar.get("enter_short", 0))

            if enter_long:
                return SignalPacket(
                    strategy_id=self.strategy_id,
                    asset_class=self.asset_class,
                    symbol=symbol,
                    direction=1.0,
                    conviction=0.80,
                    suggested_stop_pct=getattr(self._strategy_instance, "stoploss", 0.04),
                    metadata={"source": "freqtrade_adapter", "signal": "enter_long"}
                )
            elif enter_short:
                return SignalPacket(
                    strategy_id=self.strategy_id,
                    asset_class=self.asset_class,
                    symbol=symbol,
                    direction=-1.0,
                    conviction=0.80,
                    suggested_stop_pct=getattr(self._strategy_instance, "stoploss", 0.04),
                    metadata={"source": "freqtrade_adapter", "signal": "enter_short"}
                )

        except Exception as e:
            log.error("[%s] Error running Freqtrade adapter: %s", self.strategy_id, e, exc_info=True)

        return None
