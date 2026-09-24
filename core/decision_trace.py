"""
core/decision_trace.py — Decision Trace Dataclass & Shadow Logging Persistence

Captures:
1. Complete diagnostic audit record across all 9 pipeline decision gates.
2. Shadow Logging: Tracks fill model cost estimates (fees, slippage, spread, latency) vs. actual execution.
3. Meta-labeling secondary model shadow predictions and probabilities.
4. Strategy sleeve and intent tracking.
"""

from __future__ import annotations
import os
import json
import time
import threading
import logging
from dataclasses import dataclass, field, asdict
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
    
    # ── Shadow Logging & Fill Model Diagnostics ──────────────────────────────
    strategy_id: Optional[str] = None
    sleeve_id: Optional[str] = None
    expected_slippage_usd: float = 0.0
    expected_fee_usd: float = 0.0
    spread_cost_usd: float = 0.0
    simulated_latency_ms: float = 0.0
    shadow_meta_label: Optional[int] = None
    shadow_meta_probability: Optional[float] = None
    shadow_execution_discrepancy: Optional[float] = None

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

    def record_shadow_trace(
        self,
        symbol: str,
        strategy_id: str,
        sleeve_id: str,
        final_action: str,
        expected_fee_usd: float = 0.0,
        expected_slippage_usd: float = 0.0,
        spread_cost_usd: float = 0.0,
        simulated_latency_ms: float = 0.0,
        shadow_meta_label: Optional[int] = None,
        shadow_meta_probability: Optional[float] = None
    ) -> DecisionTrace:
        """Helper to create and persist a shadow trace for an order intent."""
        trace = DecisionTrace(
            symbol=symbol,
            timestamp=time.time(),
            s_composite_raw=1.0 if final_action == "EXECUTED" else 0.0,
            s_flow=0.0,
            iff_veto=False,
            iff_scaled_signal=1.0 if final_action == "EXECUTED" else 0.0,
            dead_day=False,
            dead_day_filter_mode="Percentile P10",
            effective_conviction=1.0,
            leverage=1.0,
            risk_budget_usd=1000.0,
            gate_ceiling_blocked=False,
            gate_daily_loss_blocked=False,
            gate_monthly_dd_blocked=False,
            micro_buffer_preempted=False,
            micro_buffer_reason="None",
            lob_imbalance_blocked=False,
            final_action=final_action,
            strategy_id=strategy_id,
            sleeve_id=sleeve_id,
            expected_fee_usd=expected_fee_usd,
            expected_slippage_usd=expected_slippage_usd,
            spread_cost_usd=spread_cost_usd,
            simulated_latency_ms=simulated_latency_ms,
            shadow_meta_label=shadow_meta_label,
            shadow_meta_probability=shadow_meta_probability
        )
        self.record_trace(trace)
        return trace

    def get_recent_traces(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._traces)[-limit:]
            return [t.to_dict() for t in items]

    def clear(self) -> None:
        with self._lock:
            self._traces.clear()


# Global singleton instance
decision_trace_buffer = DecisionTraceBuffer()
