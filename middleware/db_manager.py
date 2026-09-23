"""
middleware/db_manager.py — MongoDB Atlas Persistence Manager

Provides direct database querying & persistence for positions, account state, quota state,
trade execution logs, and stock screener rankings to MongoDB Atlas. Includes graceful fallback if DB is unreachable.
"""

from __future__ import annotations
import os
import time
import logging
from typing import Any, Dict, List, Optional
import config

log = logging.getLogger(__name__)

class MongoDatabaseManager:
    def __init__(self):
        self.client = None
        self.db = None
        self.connected = False
        self._init_connection()

    def _init_connection(self):
        uri = getattr(config, "MONGODB_URI", "").strip()
        if not uri or "<db_password>" in uri:
            log.info("[MongoDB] URI contains placeholder <db_password> or is unconfigured. Using in-memory store.")
            self.connected = False
            return

        try:
            import pymongo
            self.client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
            # Trigger quick ping
            self.client.admin.command('ping')
            
            # Extract DB name from URI or default to trade-db
            db_name = "trade-db"
            if "/" in uri.split("?")[0]:
                possible_name = uri.split("?")[0].split("/")[-1]
                if possible_name:
                    db_name = possible_name

            self.db = self.client[db_name]
            self.connected = True
            log.info(f"[MongoDB] Successfully connected to MongoDB Atlas ({db_name}).")
        except Exception as e:
            log.warning(f"[MongoDB] Connection failed: {e}. Falling back to in-memory store.")
            self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    # ── Account State Persistence ──────────────────────────────────────────────
    def save_account(self, account_data: Dict[str, Any]) -> bool:
        if not self.connected or self.db is None:
            return False
        try:
            self.db["account"].update_one(
                {"id": "primary_account"},
                {"$set": {"id": "primary_account", "updated_at": time.time(), **account_data}},
                upsert=True
            )
            return True
        except Exception as e:
            log.error(f"[MongoDB] Error saving account state: {e}")
            return False

    def get_account(self) -> Optional[Dict[str, Any]]:
        if not self.connected or self.db is None:
            return None
        try:
            doc = self.db["account"].find_one({"id": "primary_account"}, {"_id": 0})
            return doc
        except Exception as e:
            log.error(f"[MongoDB] Error querying account state: {e}")
            return None

    # ── Quota State Persistence ───────────────────────────────────────────────
    def save_quota(self, quota_data: Dict[str, Any]) -> bool:
        if not self.connected or self.db is None:
            return False
        try:
            self.db["quota"].update_one(
                {"id": "quota_summary"},
                {"$set": {"id": "quota_summary", "updated_at": time.time(), **quota_data}},
                upsert=True
            )
            return True
        except Exception as e:
            log.error(f"[MongoDB] Error saving quota state: {e}")
            return False

    def get_quota(self) -> Optional[Dict[str, Any]]:
        if not self.connected or self.db is None:
            return None
        try:
            doc = self.db["quota"].find_one({"id": "quota_summary"}, {"_id": 0})
            return doc
        except Exception as e:
            log.error(f"[MongoDB] Error querying quota state: {e}")
            return None

    # ── Positions Querying & Persistence ───────────────────────────────────────
    def save_position(self, symbol: str, position_data: Dict[str, Any]) -> bool:
        if not self.connected or self.db is None:
            return False
        try:
            positions_coll = self.db["positions"]
            doc = {
                "symbol": symbol,
                "qty": float(position_data.get("qty", 0.0)),
                "entry_price": float(position_data.get("entry_price", 0.0)),
                "current_price": float(position_data.get("current_price", position_data.get("entry_price", 0.0))),
                "unrealized_pl": float(position_data.get("unrealized_pl", 0.0)),
                "leverage": float(position_data.get("leverage", 10.0)),
                "updated_at": time.time()
            }
            positions_coll.update_one({"symbol": symbol}, {"$set": doc}, upsert=True)
            return True
        except Exception as e:
            log.error(f"[MongoDB] Error saving position for {symbol}: {e}")
            return False

    def remove_position(self, symbol: str) -> bool:
        if not self.connected or self.db is None:
            return False
        try:
            self.db["positions"].delete_one({"symbol": symbol})
            return True
        except Exception as e:
            log.error(f"[MongoDB] Error removing position for {symbol}: {e}")
            return False

    def get_active_positions(self) -> Dict[str, Dict[str, Any]]:
        if not self.connected or self.db is None:
            return {}
        try:
            positions_coll = self.db["positions"]
            result = {}
            for doc in positions_coll.find({}, {"_id": 0}):
                sym = doc.get("symbol")
                if sym:
                    result[sym] = doc
            return result
        except Exception as e:
            log.error(f"[MongoDB] Error querying active positions: {e}")
            return {}

    # ── Trade Execution Logs ──────────────────────────────────────────────────
    def save_trade_log(self, trade_data: Dict[str, Any]) -> bool:
        if not self.connected or self.db is None:
            return False
        try:
            trades_coll = self.db["trades"]
            trade_id = trade_data.get("trade_id") or f"trade_{int(time.time() * 1000)}"
            doc = {
                "trade_id": trade_id,
                "symbol": trade_data.get("symbol", trade_data.get("instrument", "")),
                "side": trade_data.get("side", trade_data.get("action", "")),
                "opened_at": trade_data.get("opened_at", trade_data.get("timestamp_proposed", time.time())),
                "closed_at": trade_data.get("closed_at"),
                "entry_price": float(trade_data.get("entry_price", 0.0)),
                "exit_price": float(trade_data.get("exit_price", 0.0)) if trade_data.get("exit_price") else None,
                "realized_pnl": float(trade_data.get("realized_pnl", 0.0)) if trade_data.get("realized_pnl") is not None else None,
                "status": trade_data.get("status", "closed" if trade_data.get("closed_at") else "open"),
                "created_at": time.time()
            }
            trades_coll.update_one({"trade_id": trade_id}, {"$set": doc}, upsert=True)
            return True
        except Exception as e:
            log.error(f"[MongoDB] Error saving trade log: {e}")
            return False

    def get_trade_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        if not self.connected or self.db is None:
            return []
        try:
            trades_coll = self.db["trades"]
            cursor = trades_coll.find({}, {"_id": 0}).sort("opened_at", -1).limit(limit)
            return list(cursor)
        except Exception as e:
            log.error(f"[MongoDB] Error querying trade logs: {e}")
            return []

    # ── Screener Rankings Cache ───────────────────────────────────────────────
    def save_screener_cache(self, candidates: List[Dict[str, Any]]) -> bool:
        if not self.connected or self.db is None:
            return False
        try:
            screener_coll = self.db["screener_cache"]
            doc = {
                "id": "latest_screener",
                "last_updated": time.time(),
                "top_candidates": candidates
            }
            screener_coll.update_one({"id": "latest_screener"}, {"$set": doc}, upsert=True)
            return True
        except Exception as e:
            log.error(f"[MongoDB] Error saving screener cache: {e}")
            return False

    def get_screener_cache(self) -> Optional[List[Dict[str, Any]]]:
        if not self.connected or self.db is None:
            return None
        try:
            doc = self.db["screener_cache"].find_one({"id": "latest_screener"}, {"_id": 0})
            if doc:
                return doc.get("top_candidates")
            return None
        except Exception as e:
            log.error(f"[MongoDB] Error querying screener cache: {e}")
            return None

# Global singleton database manager instance
mongo_db = MongoDatabaseManager()
