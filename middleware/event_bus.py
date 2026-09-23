"""
middleware/event_bus.py — Central Event Bus & Single Source of Truth Store

Maintains strictly-formatted position state, execution logs, and engine health
conforming to the SCHEMA.md specification.
"""

from __future__ import annotations
import time
import uuid
import threading
from datetime import datetime, timezone
from collections import deque
from typing import Dict, List, Optional, Any
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.time_utils import now_ist_iso, ts_to_ist_iso

def to_iso8601(ts: Optional[float] = None) -> str:
    """Converts unix timestamp (or current time) to IST ISO8601 string."""
    return ts_to_ist_iso(ts or time.time())

class EventBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._start_time = time.time()
        self._active_positions: Dict[str, dict] = {} # trade_id -> position dict
        self._closed_positions: deque = deque(maxlen=200) # closed position history
        self._execution_logs: deque = deque(maxlen=500) # execution log history
        self._recent_events: deque = deque(maxlen=500) # all WS events queue

    def publish_position_update(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        size: float,
        leverage: float,
        entry_price: float,
        mark_price: float,
        status: str, # "open" | "closed" | "liquidated"
        opened_at: str,
        exit_price: Optional[float] = None,
        unrealized_pnl: Optional[float] = None,
        realized_pnl: Optional[float] = None,
        closed_at: Optional[str] = None
    ) -> dict:
        """
        Constructs a SCHEMA.md compliant position_update event.
        Guarantees all keys are present (using None/null when inapplicable).
        """
        clean_side = side.lower() if side else "long"
        clean_status = status.lower() if status else "open"
        
        # Calculate pure mark-to-market unrealized PnL if not explicitly passed
        if unrealized_pnl is None and clean_status == "open":
            mult = 1.0 if clean_side == "long" else -1.0
            unrealized_pnl = round((mark_price - entry_price) * size * mult, 2)

        data = {
            "trade_id": trade_id,
            "symbol": symbol,
            "side": clean_side,
            "size": round(abs(size), 4),
            "leverage": round(float(leverage), 2),
            "entry_price": round(float(entry_price), 4),
            "exit_price": round(float(exit_price), 4) if exit_price is not None else None,
            "mark_price": round(float(mark_price), 4),
            "unrealized_pnl": round(float(unrealized_pnl), 2) if unrealized_pnl is not None else 0.0,
            "realized_pnl": round(float(realized_pnl), 2) if realized_pnl is not None else None,
            "status": clean_status,
            "opened_at": opened_at,
            "closed_at": closed_at if clean_status != "open" else None
        }

        event = {
            "type": "position_update",
            "timestamp": to_iso8601(),
            "data": data
        }

        with self._lock:
            if clean_status == "open":
                self._active_positions[trade_id] = data
            else:
                if trade_id in self._active_positions:
                    del self._active_positions[trade_id]
                self._closed_positions.append(data)
            self._recent_events.append(event)

        # Sync to MongoDB database manager if connected
        try:
            from middleware.db_manager import mongo_db
            if mongo_db.is_connected():
                if clean_status == "open":
                    mongo_db.save_position(symbol, data)
                else:
                    mongo_db.remove_position(symbol)
                    mongo_db.save_trade_log(data)
        except Exception:
            pass

        return event

    def publish_execution_log(
        self,
        level: str, # "info" | "warn" | "error" | "fill"
        category: str,
        symbol: str,
        message: str,
        order_id: Optional[str] = None,
        log_id: Optional[str] = None
    ) -> dict:
        """
        Constructs a SCHEMA.md compliant execution_log event.
        """
        data = {
            "log_id": log_id or f"log_{uuid.uuid4().hex[:8]}",
            "level": level.lower(),
            "category": category,
            "symbol": symbol,
            "message": message,
            "order_id": order_id
        }

        event = {
            "type": "execution_log",
            "timestamp": to_iso8601(),
            "data": data
        }

        with self._lock:
            self._execution_logs.append(data)
            self._recent_events.append(event)

        return event

    def get_engine_health(self) -> dict:
        """
        Constructs a SCHEMA.md compliant engine_health payload.
        """
        uptime = int(time.time() - self._start_time)
        with self._lock:
            active_count = len(self._active_positions)

        data = {
            "status": "healthy",
            "uptime_seconds": uptime,
            "last_heartbeat": to_iso8601(),
            "connected_exchanges": {
                "binance": "connected",
                "alpaca": "connected"
            },
            "active_positions_count": active_count
        }

        return {
            "type": "engine_health",
            "timestamp": to_iso8601(),
            "data": data
        }

    def get_active_positions(self) -> List[dict]:
        with self._lock:
            return list(self._active_positions.values())

    def get_all_positions(self) -> List[dict]:
        with self._lock:
            return list(self._active_positions.values()) + list(self._closed_positions)

    def get_execution_logs(self) -> List[dict]:
        with self._lock:
            return list(self._execution_logs)

    def get_recent_events(self) -> List[dict]:
        with self._lock:
            return list(self._recent_events)

# Singleton Event Bus Instance
event_bus = EventBus()
