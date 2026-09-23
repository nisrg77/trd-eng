"""
core/symbol_state.py — Consolidated Thread-Safe Per-Symbol State Manager

Single source of truth for symbol-level historical metrics (ATR, RVOL, Volatility)
and tick-level order flow (OBI/flow_score ticks), guarded by per-symbol locks.
"""

from __future__ import annotations
import threading
from collections import deque
from typing import Dict, List, Tuple, Optional
import numpy as np

class SymbolState:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self._lock = threading.Lock()
        
        # Historical deques for dead day & volatility percentile calculation
        self.range_atr_history: deque[float] = deque(maxlen=252)
        self.rvol_history: deque[float] = deque(maxlen=252)
        self.realized_vol_history: deque[float] = deque(maxlen=252)
        
        # Tick-level flow score history: (timestamp, flow_score)
        self.flow_ticks: deque[Tuple[float, float]] = deque(maxlen=500)

    def add_range_atr(self, val: float) -> None:
        with self._lock:
            self.range_atr_history.append(float(val))

    def add_rvol(self, val: float) -> None:
        with self._lock:
            self.rvol_history.append(float(val))

    def add_realized_vol(self, val: float) -> None:
        with self._lock:
            self.realized_vol_history.append(float(val))

    def record_flow_tick(self, ts: float, flow_score: float) -> None:
        with self._lock:
            self.flow_ticks.append((float(ts), float(flow_score)))

    def get_percentile_thresholds(self, percentile_p10: float = 10.0) -> Tuple[Optional[float], Optional[float]]:
        """
        Returns (range_atr_p10, rvol_p10) computed from history if history >= 30 bars,
        otherwise returns (None, None).
        """
        with self._lock:
            if len(self.range_atr_history) < 30 or len(self.rvol_history) < 30:
                return None, None
            
            p_range = float(np.percentile(list(self.range_atr_history), percentile_p10))
            p_rvol = float(np.percentile(list(self.rvol_history), percentile_p10))
            return p_range, p_rvol

    def get_recent_flow_ticks(self, window_seconds: float) -> List[Tuple[float, float]]:
        """
        Returns flow ticks recorded within the last window_seconds.
        """
        with self._lock:
            if not self.flow_ticks:
                return []
            now = self.flow_ticks[-1][0]
            cutoff = now - window_seconds
            return [t for t in self.flow_ticks if t[0] >= cutoff]

    def clear(self) -> None:
        with self._lock:
            self.range_atr_history.clear()
            self.rvol_history.clear()
            self.realized_vol_history.clear()
            self.flow_ticks.clear()


class SymbolStateRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._states: Dict[str, SymbolState] = {}

    def get(self, symbol: str) -> SymbolState:
        symbol = symbol.upper().strip()
        with self._lock:
            if symbol not in self._states:
                self._states[symbol] = SymbolState(symbol)
            return self._states[symbol]

    def clear(self) -> None:
        with self._lock:
            for s in self._states.values():
                s.clear()
            self._states.clear()


# Global singleton symbol state registry instance
symbol_state_registry = SymbolStateRegistry()
