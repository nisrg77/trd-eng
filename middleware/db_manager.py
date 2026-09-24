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
        self._in_memory_strategies: Dict[str, Dict[str, Any]] = {}
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
            # Sync positions collection with active positions from account
            if "positions" in account_data and isinstance(account_data["positions"], dict):
                positions_coll = self.db["positions"]
                active_symbols = set()
                for sym, pos_data in account_data["positions"].items():
                    qty_val = float(pos_data.get("qty", 0.0))
                    if abs(qty_val) < 1e-7:
                        continue
                    active_symbols.add(sym)
                    entry_p = float(pos_data.get("entry_price", pos_data.get("price", 0.0)))
                    curr_p = float(pos_data.get("current_price", pos_data.get("mark_price", entry_p)))
                    unrl_pl = float(pos_data.get("unrealized_pl", pos_data.get("unrealized_pnl", 0.0)))
                    doc = {
                        "trade_id": pos_data.get("trade_id", ""),
                        "symbol": sym,
                        "side": pos_data.get("side", "long" if qty_val >= 0 else "short"),
                        "qty": qty_val,
                        "size": abs(qty_val),
                        "entry_price": entry_p,
                        "current_price": curr_p,
                        "mark_price": curr_p,
                        "unrealized_pl": unrl_pl,
                        "unrealized_pnl": unrl_pl,
                        "leverage": float(pos_data.get("leverage", 10.0)),
                        "status": "open",
                        "opened_at": pos_data.get("opened_at", ""),
                        "updated_at": time.time()
                    }
                    positions_coll.update_one({"symbol": sym}, {"$set": doc}, upsert=True)
                # Clean up any stale positions in positions collection not present in active_symbols
                if active_symbols:
                    positions_coll.delete_many({"symbol": {"$nin": list(active_symbols)}})
                else:
                    positions_coll.delete_many({})
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
            qty_raw = position_data.get("qty")
            if qty_raw is None:
                qty_raw = position_data.get("size", 0.0)
                if str(position_data.get("side", "")).lower() == "short":
                    qty_raw = -abs(float(qty_raw))
            qty_val = float(qty_raw or 0.0)
            entry_p = float(position_data.get("entry_price", position_data.get("price", 0.0)))
            curr_p = float(position_data.get("current_price", position_data.get("mark_price", entry_p)))
            unrl_pl = float(position_data.get("unrealized_pl", position_data.get("unrealized_pnl", 0.0)))
            doc = {
                "trade_id": position_data.get("trade_id", ""),
                "symbol": symbol,
                "side": position_data.get("side", "long" if qty_val >= 0 else "short"),
                "qty": qty_val,
                "size": abs(qty_val),
                "entry_price": entry_p,
                "current_price": curr_p,
                "mark_price": curr_p,
                "unrealized_pl": unrl_pl,
                "unrealized_pnl": unrl_pl,
                "leverage": float(position_data.get("leverage", 10.0)),
                "status": position_data.get("status", "open"),
                "opened_at": position_data.get("opened_at", ""),
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

            # Cross-reference with primary_account positions to recover any 0.0 qty or missing entries
            acc = self.db["account"].find_one({"id": "primary_account"}, {"_id": 0})
            if acc and "positions" in acc and isinstance(acc["positions"], dict):
                for sym, pos_data in acc["positions"].items():
                    qty_val = float(pos_data.get("qty", 0.0))
                    if abs(qty_val) > 1e-7:
                        # If positions collection is missing sym or has 0 qty, repair it
                        if sym not in result or abs(float(result[sym].get("qty", 0.0))) < 1e-7:
                            result[sym] = {
                                "trade_id": pos_data.get("trade_id", ""),
                                "symbol": sym,
                                "side": pos_data.get("side", "long" if qty_val >= 0 else "short"),
                                "qty": qty_val,
                                "size": abs(qty_val),
                                "entry_price": float(pos_data.get("entry_price", 0.0)),
                                "current_price": float(pos_data.get("current_price", pos_data.get("entry_price", 0.0))),
                                "mark_price": float(pos_data.get("current_price", pos_data.get("entry_price", 0.0))),
                                "unrealized_pl": float(pos_data.get("unrealized_pl", 0.0)),
                                "unrealized_pnl": float(pos_data.get("unrealized_pl", 0.0)),
                                "leverage": float(pos_data.get("leverage", 10.0)),
                                "status": "open",
                                "opened_at": pos_data.get("opened_at", ""),
                                "updated_at": pos_data.get("updated_at", time.time())
                            }
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

    # ── Gate Rejection Log ────────────────────────────────────────────────────
    def save_gate_rejection(self, rejection: Dict[str, Any]) -> bool:
        """
        Persists a structured gate rejection record to the `gate_rejections` collection.

        Expected keys in `rejection`:
          instrument       str   — ticker / pair
          asset_class      str   — 'crypto' | 'stock'
          gate             str   — gate layer name, e.g. 'GOAL_GATE', 'LOW_CONVICTION', ...
          reason           str   — human-readable block reason from that gate
          final_action     str   — mirrors DecisionTrace.final_action
          signal_direction float — raw directional magnitude from the signal
          effective_conviction float
          daily_trades_used    int
          monthly_pnl_usd      float
        """
        if not self.connected or self.db is None:
            log.debug("[MongoDB] gate_rejection not persisted — no connection.")
            return False
        try:
            doc = {
                "rejection_id": f"rej_{int(time.time() * 1000)}",
                "timestamp": time.time(),
                "instrument": rejection.get("instrument", ""),
                "asset_class": rejection.get("asset_class", ""),
                "gate": rejection.get("gate", "UNKNOWN"),
                "reason": rejection.get("reason", ""),
                "final_action": rejection.get("final_action", ""),
                "signal_direction": float(rejection.get("signal_direction", 0.0)),
                "effective_conviction": float(rejection.get("effective_conviction", 0.0)),
                "daily_trades_used": int(rejection.get("daily_trades_used", 0)),
                "monthly_pnl_usd": float(rejection.get("monthly_pnl_usd", 0.0)),
            }
            self.db["gate_rejections"].insert_one(doc)
            return True
        except Exception as e:
            log.error(f"[MongoDB] Error saving gate rejection: {e}")
            return False

    def get_gate_rejections(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Returns the most recent gate rejection records, newest first."""
        if not self.connected or self.db is None:
            return []
        try:
            cursor = self.db["gate_rejections"].find({}, {"_id": 0}).sort("timestamp", -1).limit(limit)
            return list(cursor)
        except Exception as e:
            log.error(f"[MongoDB] Error querying gate rejections: {e}")
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

    # ── Strategies Collection & Hot-Reloading ────────────────────────────────
    def save_strategy(self, strategy_data: Dict[str, Any]) -> bool:
        """Saves or updates a strategy document."""
        strat_id = strategy_data.get("strategy_id")
        if not strat_id:
            return False

        doc = dict(strategy_data)
        doc["updated_at"] = time.time()
        self._in_memory_strategies[strat_id] = doc

        if not self.connected or self.db is None:
            return True

        try:
            self.db["strategies"].update_one(
                {"strategy_id": strat_id},
                {"$set": doc},
                upsert=True
            )
            return True
        except Exception as e:
            log.error(f"[MongoDB] Error saving strategy {strat_id}: {e}")
            return False

    def get_strategy(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a strategy document by ID."""
        if self.connected and self.db is not None:
            try:
                doc = self.db["strategies"].find_one({"strategy_id": strategy_id}, {"_id": 0})
                if doc:
                    return doc
            except Exception as e:
                log.error(f"[MongoDB] Error querying strategy {strategy_id}: {e}")

        return self._in_memory_strategies.get(strategy_id)

    def list_strategies(self, asset_class: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists all registered strategies, optionally filtered by asset class."""
        if self.connected and self.db is not None:
            try:
                query = {}
                if asset_class:
                    query["asset_class"] = asset_class.lower()
                cursor = self.db["strategies"].find(query, {"_id": 0})
                return list(cursor)
            except Exception as e:
                log.error(f"[MongoDB] Error listing strategies: {e}")

        # Fallback to in-memory
        res = list(self._in_memory_strategies.values())
        if asset_class:
            ac_lower = asset_class.lower()
            res = [s for s in res if s.get("asset_class", "").lower() == ac_lower]
        return res

    def update_strategy_params(self, strategy_id: str, new_params: Dict[str, Any]) -> bool:
        """Hot-reloads hyperparameters for a strategy."""
        strat = self.get_strategy(strategy_id)
        if not strat:
            return False

        params = strat.get("parameters", {})
        params.update(new_params)
        strat["parameters"] = params
        return self.save_strategy(strat)

    def update_strategy_status(self, strategy_id: str, new_status: str) -> bool:
        """Updates status ('active' | 'inactive') for a strategy."""
        strat = self.get_strategy(strategy_id)
        if not strat:
            return False
        strat["status"] = new_status
        return self.save_strategy(strat)

# Global singleton database manager instance
mongo_db = MongoDatabaseManager()
