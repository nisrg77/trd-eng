"""
scripts/audit_redundancy.py — Cross-Layer Redundancy & Gate Audit Script

Parses DecisionTrace records from MongoDB Atlas or decision_trace.jsonl to compute:
1. HMM regime vs Dead-Day filter agreement / correlation per symbol.
2. Overlap rate between LOB imbalance filter blocks and Micro-Buffer veto blocks.
3. Frequency distribution of all final_action block reasons across observed history.
"""

from __future__ import annotations
import os
import sys
import json
import logging
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

log = logging.getLogger(__name__)

TRACE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "decision_trace.jsonl")

def load_decision_traces() -> list[dict]:
    """Loads decision traces from MongoDB Atlas if connected, otherwise reads decision_trace.jsonl."""
    try:
        from middleware.db_manager import mongo_db
        if mongo_db.is_connected() and mongo_db.db is not None:
            docs = list(mongo_db.db["decision_traces"].find({}, {"_id": 0}))
            if docs:
                log.info(f"[Audit] Loaded {len(docs)} trace records from MongoDB Atlas.")
                return docs
    except Exception as e:
        log.warning(f"[Audit] MongoDB query skipped: {e}")

    if not os.path.exists(TRACE_FILE):
        log.warning(f"[Audit] Trace file {TRACE_FILE} not found.")
        return []

    traces = []
    try:
        with open(TRACE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    traces.append(json.loads(line))
        log.info(f"[Audit] Loaded {len(traces)} trace records from local JSONL log.")
    except Exception as e:
        log.error(f"[Audit] Error reading {TRACE_FILE}: {e}")

    return traces


def run_redundancy_audit():
    traces = load_decision_traces()
    if not traces:
        print("\n[Audit Report] No decision traces found. Run paper trading to populate traces.\n")
        return

    total_records = len(traces)
    action_counts = Counter(t.get("final_action", "UNKNOWN") for t in traces)

    symbol_dead_days = defaultdict(int)
    symbol_total = defaultdict(int)

    lob_and_micro_both = 0
    lob_only = 0
    micro_only = 0

    for t in traces:
        sym = t.get("symbol", "UNKNOWN")
        symbol_total[sym] += 1
        if t.get("dead_day", False):
            symbol_dead_days[sym] += 1

        lob_blocked = t.get("lob_imbalance_blocked", False)
        micro_blocked = t.get("micro_buffer_preempted", False)

        if lob_blocked and micro_blocked:
            lob_and_micro_both += 1
        elif lob_blocked:
            lob_only += 1
        elif micro_blocked:
            micro_only += 1

    print("\n" + "=" * 70)
    print(f"   TRDENG CROSS-LAYER REDUNDANCY AUDIT REPORT ({total_records} RECORDS)")
    print("=" * 70)

    print("\n1. GATE BLOCK FREQUENCY DISTRIBUTION:")
    print("-" * 50)
    for action, count in action_counts.most_common():
        pct = (count / total_records) * 100
        print(f"  * {action:<30}: {count:>5} ({pct:>5.1f}%)")

    print("\n2. DEAD-DAY FILTER FREQUENCY BY SYMBOL:")
    print("-" * 50)
    for sym, count in symbol_total.items():
        dead_cnt = symbol_dead_days[sym]
        pct = (dead_cnt / count) * 100 if count > 0 else 0.0
        print(f"  * {sym:<12}: {dead_cnt:>4} / {count:>4} dead days ({pct:>5.1f}%)")

    print("\n3. LOB IMBALANCE vs MICRO-BUFFER VETO OVERLAP RATE:")
    print("-" * 50)
    print(f"  * Micro-Buffer Veto Only  : {micro_only:>5}")
    print(f"  * LOB Imbalance Only      : {lob_only:>5}")
    print(f"  * Dual Veto Overlap       : {lob_and_micro_both:>5}")
    if (micro_only + lob_only + lob_and_micro_both) > 0:
        overlap_rate = (lob_and_micro_both / (micro_only + lob_only + lob_and_micro_both)) * 100
        print(f"  * Overlap Percentage      : {overlap_rate:>5.1f}%")
    else:
        print("  * Overlap Percentage      : N/A (no vetoes recorded yet)")

    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_redundancy_audit()
