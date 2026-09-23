"""
core/decision_trace.py — Decision Trace Dataclass & Persistence Manager

Captures a complete 17-field diagnostic audit record for every proposed order (executed or blocked)
across all 9 pipeline decision gates.
"""

from __future__ import annotations
import os
import json
import time
import threading
import logging
from dataclasses import dataclass, asdict
from collections import deque
from typing import List, Dict, Any, Optional

log = logging.getLogger(__name__)

TRACE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "decision_trace.jsonl")

@dataclass
class DecisionTrace:
    symbol: str
    timestamp: float
    s_composite_raw: float
    s_flow: float
    iff_veto: bool
    iff_scaled_signal: float
    dead_day: bool
    dead_day_filter_mode: str        # "Percentile P10" or "Static Fallback"
    effective_conviction: float
    leverage: float
    risk_budget_usd: float
    gate_ceiling_blocked: bool
    gate_daily_loss_blocked: bool
    gate_monthly_dd_blocked: bool
    micro_buffer_preempted: bool
    micro_buffer_reason: str
    lob_imbalance_blocked: bool
    final_action: str                # "EXECUTED" | "BLOCKED_<gate_name>"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DecisionTraceBuffer:
    def __init__(self, maxlen: int = 1000):
        self._lock = threading.Lock()
        self._traces: deque[DecisionTrace] = deque(maxlen=maxlen)

    def record_trace(self, trace: DecisionTrace) -> None:
        dict_data = trace.to_dict()
        with self._lock:
            self._traces.append(trace)

        # 1. Append to local decision_trace.jsonl file
        try:
            with open(TRACE_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(dict_data) + "\n")
        except Exception as e:
            log.error(f"[DecisionTrace] Error writing trace to JSONL: {e}")

        # 2. Sync to MongoDB Atlas decision_traces collection if connected
        try:
            from middleware.db_manager import mongo_db
            if mongo_db.is_connected() and mongo_db.db is not None:
                mongo_db.db["decision_traces"].insert_one(dict_data)
        except Exception:
            pass

    def get_recent_traces(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._traces)[-limit:]
            return [t.to_dict() for t in items]

    def clear(self) -> None:
        with self._lock:
            self._traces.clear()


# Global singleton instance
decision_trace_buffer = DecisionTraceBuffer()
