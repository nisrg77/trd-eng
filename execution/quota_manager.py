"""
execution/quota_manager.py — Compatibility Adapter for Goal & Risk Gating Module

Delegates all quota, progress, and trade logging calls directly to
goals.goal_module to prevent split-brain state or race conditions.
"""

import os
import json
import logging
import threading
from goals.goal_module import goal_module, record_trade_result, evaluate_trade

log = logging.getLogger(__name__)

class QuotaManager:
    def __init__(self):
        self.target_crypto = 20
        self.target_futures = 80

    def can_trade(self, asset_class: str) -> bool:
        """Returns True if the pipeline is allowed to trade based on GoalModule."""
        state = goal_module.load_state()
        ac = asset_class.lower()
        if ac in ["crypto"]:
            return state["crypto"]["completed"] < self.target_crypto
        elif ac in ["futures", "stock", "stocks"]:
            return state["stocks"]["completed"] < self.target_futures
        return False

    def is_baseline_complete(self) -> bool:
        """Returns True if monthly trade ceilings are reached."""
        state = goal_module.load_state()
        return (state["crypto"]["completed"] >= self.target_crypto and 
                state["stocks"]["completed"] >= self.target_futures)

    def log_closed_trade(self, asset_class: str, pnl: float):
        """Logs a closed trade via GoalModule."""
        ac = "crypto" if asset_class.lower() == "crypto" else "stock"
        record_trade_result(ac, pnl)

# Singleton
quota_manager = QuotaManager()

