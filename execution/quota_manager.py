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
        ac = "crypto" if asset_class.lower() == "crypto" else "stock"
        bucket = state.bucket(ac)
        target = self.target_crypto if ac == "crypto" else self.target_futures
        return bucket.trades_today < target

    def is_baseline_complete(self) -> bool:
        """Returns True if daily trade ceilings are reached."""
        state = goal_module.load_state()
        return (state.crypto.trades_today >= self.target_crypto and 
                state.stock.trades_today >= self.target_futures)

    def log_closed_trade(self, asset_class: str, pnl: float):
        """Logs a closed trade via GoalModule."""
        ac = "crypto" if asset_class.lower() == "crypto" else "stock"
        record_trade_result(ac, pnl)

# Singleton
quota_manager = QuotaManager()

