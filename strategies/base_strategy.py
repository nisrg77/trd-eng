"""
strategies/base_strategy.py — Standard Strategy Interface (Protocol)

Strict base class for all plug-and-play quantitative strategies.
Pure function guarantee: Strategy takes data in -> returns a SignalPacket.
It NEVER places orders, touches brokers, or modifies global execution state.
"""

from __future__ import annotations
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import pandas as pd
from core.signal_packet import SignalPacket

log = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """
    Abstract Base Class for all TRDENG strategies.
    
    Subclasses must implement `generate_signal(symbol, df)`.
    """

    def __init__(
        self,
        strategy_id: str,
        name: str,
        asset_class: str,
        params: Optional[Dict[str, Any]] = None,
        is_active: bool = True
    ) -> None:
        self.strategy_id = strategy_id
        self.name = name
        self.asset_class = asset_class.lower()  # "crypto" or "stock" / "futures"
        self.params: Dict[str, Any] = params or {}
        self.is_active = is_active
        self._execution_count = 0
        self._last_signal: Optional[SignalPacket] = None

    @abstractmethod
    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Optional[SignalPacket]:
        """
        Pure function: Evaluates current symbol history/features and emits a SignalPacket.
        
        Parameters:
            symbol: Ticker symbol (e.g. 'BTC-USD', 'AAPL').
            df: Feature-enriched pandas DataFrame with at least OHLCV data.
            
        Returns:
            SignalPacket with direction and conviction, or None if no setup exists.
        """
        pass

    def update_parameters(self, new_params: Dict[str, Any]) -> None:
        """
        Hot-reloads strategy hyperparameters without restarting the process.
        """
        old_params = dict(self.params)
        self.params.update(new_params)
        log.info(
            "[%s] Hyperparameters updated: %s -> %s",
            self.strategy_id,
            old_params,
            self.params
        )

    def set_active(self, active: bool) -> None:
        """Toggles strategy active state."""
        self.is_active = active
        log.info("[%s] Strategy active state set to %s", self.strategy_id, active)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes strategy metadata for database and API presentation."""
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "asset_class": self.asset_class,
            "is_active": self.is_active,
            "parameters": self.params,
            "execution_count": self._execution_count,
            "last_signal": self._last_signal.to_dict() if self._last_signal else None,
        }
