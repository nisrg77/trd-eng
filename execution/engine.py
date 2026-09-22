"""
execution/engine.py — Execution & Sizing Engine (EE)

Pulls standard signals from the Core Brain, applies position sizing
logic (Kelly Criterion, scaled by confidence), and constructs a proposed
order for the Risk Guard.
"""

from __future__ import annotations
import uuid
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

class ExecutionEngine:
    def __init__(self):
        pass

    def size_order(self, signal: dict, instrument_data: dict) -> dict | None:
        """
        Calculates position size and generates a proposed order.
        If current position is highly profitable, takes partial profit instead.
        Returns None if confidence is too low.
        """
        instr = signal.get("instrument")
        confidence = signal.get("confidence_score", 0.0)
        direction = signal.get("direction_magnitude", 0.0)
        
        # Pull the active risk profile settings
        prof_name = config.ACTIVE_RISK_PROFILE
        profile = config.RISK_PROFILES.get(prof_name, config.RISK_PROFILES["Balanced"])
        
        # 1. Check for Partial Take-Profit opportunities
        if instr in instrument_data:
            pos = instrument_data[instr]
            if pos["unrealized_plpc"] >= profile["PARTIAL_TP_THRESHOLD_PCT"]:
                action = "SELL" if pos["exposure_pct"] > 0 else "BUY" # Covering short if supported
                alloc_pct = pos["exposure_pct"] * profile["PARTIAL_TP_SELL_PCT"]
                
                order_id = "ord_tp_" + uuid.uuid4().hex[:8]
                return {
                    "order_id": order_id,
                    "signal_id": signal.get("signal_id"),
                    "instrument": instr,
                    "action": action,
                    "order_type": "MARKET",
                    "portfolio_allocation_pct": alloc_pct,
                    "confidence": 1.0, # High confidence for TP
                    "timestamp_proposed": time.time(),
                    "is_take_profit": True
                }

        # 2. Normal Signal Processing
        if confidence < config.MIN_CONFIDENCE_THRESHOLD:
            return None # Ignore low-confidence signals

        allocation_pct = confidence * profile["KELLY_FRACTION"]
        allocation_pct = min(allocation_pct, profile["MAX_POSITION_SIZE_PCT"])

        # Ensure minimum size
        if allocation_pct < 0.01:
            return None

        action = "BUY" if direction > 0 else "SELL" if direction < 0 else "HOLD"
        
        if action == "HOLD":
            return None

        order_id = "ord_" + uuid.uuid4().hex[:8]

        proposed_order = {
            "order_id": order_id,
            "signal_id": signal.get("signal_id"),
            "instrument": signal.get("instrument"),
            "action": action,
            "order_type": "MARKET", # Using MARKET for simplicity in paper trading
            "portfolio_allocation_pct": allocation_pct,
            "confidence": confidence,
            "timestamp_proposed": time.time(),
            "is_take_profit": False
        }

        return proposed_order
