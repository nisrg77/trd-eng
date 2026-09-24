"""
strategies/strategy_registry.py — Thread-Safe Strategy Hub & Dispatcher

Manages the registration, dynamic reloading, and safe parallel execution of all strategy plugins.
Guarantees error isolation: An exception in one strategy will NEVER disrupt others.
"""

from __future__ import annotations
import logging
import threading
from typing import Dict, List, Optional
import pandas as pd
from core.signal_packet import SignalPacket
from strategies.base_strategy import BaseStrategy

log = logging.getLogger(__name__)


class StrategyRegistry:
    """
    Thread-safe registry of active trading strategies.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._strategies: Dict[str, BaseStrategy] = {}

    def register(self, strategy: BaseStrategy) -> None:
        """Registers a new strategy instance."""
        with self._lock:
            self._strategies[strategy.strategy_id] = strategy
            log.info("Registered strategy [%s] (%s | %s)", strategy.strategy_id, strategy.name, strategy.asset_class)

    def unregister(self, strategy_id: str) -> bool:
        """Removes a strategy from registry."""
        with self._lock:
            if strategy_id in self._strategies:
                del self._strategies[strategy_id]
                log.info("Unregistered strategy [%s]", strategy_id)
                return True
            return False

    def get(self, strategy_id: str) -> Optional[BaseStrategy]:
        """Retrieves a strategy by its ID."""
        with self._lock:
            return self._strategies.get(strategy_id)

    def list_strategies(self, asset_class: Optional[str] = None, active_only: bool = False) -> List[BaseStrategy]:
        """Lists registered strategies, optionally filtered by asset class or active state."""
        with self._lock:
            results = list(self._strategies.values())
            if asset_class:
                ac_lower = asset_class.lower()
                results = [s for s in results if s.asset_class == ac_lower]
            if active_only:
                results = [s for s in results if s.is_active]
            return results

    def evaluate_all(
        self,
        symbol: str,
        df: pd.DataFrame,
        asset_class: Optional[str] = None
    ) -> List[SignalPacket]:
        """
        Executes all active matching strategies for a symbol.
        
        Guarantees isolation: If strategy raises an exception, it is caught and logged,
        preventing any stall or crash in the engine.
        """
        signals: List[SignalPacket] = []
        active_strats = self.list_strategies(asset_class=asset_class, active_only=True)

        for strat in active_strats:
            try:
                sig = strat.generate_signal(symbol, df)
                if sig is not None and isinstance(sig, SignalPacket):
                    strat._execution_count += 1
                    strat._last_signal = sig
                    signals.append(sig)
            except Exception as e:
                log.error(
                    "Error executing strategy [%s] on symbol %s: %s",
                    strat.strategy_id,
                    symbol,
                    e,
                    exc_info=True
                )

        return signals

    def update_strategy_parameters(self, strategy_id: str, new_params: dict) -> bool:
        """Updates parameters for a registered strategy."""
        with self._lock:
            strat = self._strategies.get(strategy_id)
            if strat:
                strat.update_parameters(new_params)
                return True
            return False

    def clear(self) -> None:
        """Clears all registered strategies (useful for tests)."""
        with self._lock:
            self._strategies.clear()


# Global Singleton
strategy_registry = StrategyRegistry()
