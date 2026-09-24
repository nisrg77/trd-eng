"""
services/chart_feed.py — High-Performance Live Chart Candlestick & Tick Feed

Dedicated streaming engine for the Live Chart WebSocket (/ws/charts).
Maintains rolling in-memory OHLCV candle histories and real-time tick aggregation
for any requested instrument and timeframe. Zero disk I/O, zero cross-talk with
portfolio or order risk evaluations.
"""

from __future__ import annotations
import time
import random
import threading
from collections import deque
from typing import Dict, List, Optional, Tuple
from middleware.ws_schema import CandleBarSchema, HistoricalCandlesPayload, format_ws_event, WSEventType


class ChartSymbolBuffer:
    """
    Thread-safe rolling buffer of historical candles and current forming bar for a symbol.
    """
    def __init__(self, symbol: str, timeframe_seconds: int = 5, max_history: int = 500):
        self.symbol = symbol.upper().strip()
        self.timeframe_seconds = max(1, timeframe_seconds)
        self.max_history = max_history
        self._lock = threading.Lock()
        self.history: deque[dict] = deque(maxlen=max_history)
        self.current_bar: Optional[dict] = None
        self.last_price: float = 100.0

    def seed_initial_history(self, base_price: float, count: int = 50) -> None:
        """
        Seeds deterministic historical bars if history is empty.
        Guarantees strictly increasing timestamps and non-zero volume.
        """
        with self._lock:
            if len(self.history) >= count:
                return

            self.last_price = base_price
            now_sec = (int(time.time()) // self.timeframe_seconds) * self.timeframe_seconds
            p = base_price
            candles: List[dict] = []

            for i in range(count, 0, -1):
                t = now_sec - (i * self.timeframe_seconds)
                var = max(0.02, p * 0.0003)
                o = round(p + random.uniform(-var, var), 2)
                h = round(max(o, p) + random.uniform(0.01, var), 2)
                l = round(min(o, p) - random.uniform(0.01, var), 2)
                c = round(p, 2)
                v = round(random.uniform(5.0, 100.0), 2)
                candles.append({
                    "time": t,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": v,
                    "symbol": self.symbol,
                    "timeframe": f"{self.timeframe_seconds}s",
                    "is_bar_closed": True
                })
                p = c

            self.history.clear()
            self.history.extend(candles)
            if candles:
                self.last_price = candles[-1]["close"]

    def ingest_tick(self, price: float, volume: float = 1.0, timestamp: Optional[float] = None) -> dict:
        """
        Ingests a real-time price tick and updates or rolls the current bar.
        Returns the updated candle bar dictionary.
        """
        ts = timestamp or time.time()
        bar_time = (int(ts) // self.timeframe_seconds) * self.timeframe_seconds
        price = round(float(price), 2)
        volume = round(float(volume), 4)

        with self._lock:
            self.last_price = price

            if self.current_bar is None:
                self.current_bar = {
                    "time": bar_time,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": max(0.1, volume),
                    "symbol": self.symbol,
                    "timeframe": f"{self.timeframe_seconds}s",
                    "is_bar_closed": False
                }
                return dict(self.current_bar)

            if bar_time > self.current_bar["time"]:
                # Seal the previous bar and push into historical deque
                sealed = dict(self.current_bar)
                sealed["is_bar_closed"] = True
                self.history.append(sealed)

                # Initialize next bar
                self.current_bar = {
                    "time": bar_time,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": max(0.1, volume),
                    "symbol": self.symbol,
                    "timeframe": f"{self.timeframe_seconds}s",
                    "is_bar_closed": False
                }
            else:
                # Update developing bar in-place
                self.current_bar["high"] = max(self.current_bar["high"], price)
                self.current_bar["low"] = min(self.current_bar["low"], price)
                self.current_bar["close"] = price
                self.current_bar["volume"] = round(self.current_bar["volume"] + volume, 4)

            return dict(self.current_bar)

    def get_historical_candles(self, limit: int = 50) -> List[dict]:
        """Returns sorted historical candles list."""
        with self._lock:
            history_list = list(self.history)
            if self.current_bar:
                history_list.append(dict(self.current_bar))
            return history_list[-limit:]


class ChartFeedManager:
    """
    Global manager for live chart feeds across all symbols and intervals.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._buffers: Dict[str, ChartSymbolBuffer] = {}

    def get_buffer(self, symbol: str, timeframe_seconds: int = 5) -> ChartSymbolBuffer:
        key = f"{symbol.upper().strip()}:{timeframe_seconds}"
        with self._lock:
            if key not in self._buffers:
                self._buffers[key] = ChartSymbolBuffer(symbol, timeframe_seconds=timeframe_seconds)
            return self._buffers[key]

    def get_initial_candles(self, symbol: str, base_price: float, count: int = 50, timeframe_seconds: int = 5) -> List[dict]:
        buf = self.get_buffer(symbol, timeframe_seconds=timeframe_seconds)
        buf.seed_initial_history(base_price=base_price, count=count)
        return buf.get_historical_candles(limit=count)

    def update_tick(self, symbol: str, price: float, volume: float = 1.0, timeframe_seconds: int = 5) -> dict:
        buf = self.get_buffer(symbol, timeframe_seconds=timeframe_seconds)
        return buf.ingest_tick(price=price, volume=volume)

    def generate_simulated_tick(self, symbol: str, base_price: float, timeframe_seconds: int = 5) -> dict:
        """
        Creates a micro-jitter tick for paper trading / live simulation when no external feed is active.
        """
        buf = self.get_buffer(symbol, timeframe_seconds=timeframe_seconds)
        cur_p = buf.last_price if buf.last_price > 0 else base_price
        max_var = max(0.02, cur_p * 0.00015)
        sub_var = random.uniform(-max_var, max_var)
        tick_p = round(max(1.0, cur_p + sub_var), 2)
        vol = round(random.uniform(0.1, 2.0), 2)
        return buf.ingest_tick(price=tick_p, volume=vol)


# Singleton Chart Feed Manager
chart_feed_manager = ChartFeedManager()
