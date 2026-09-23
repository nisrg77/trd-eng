"""
middleware/telemetry_db.py — Local SQLite DB for Headless Telemetry

Logs latency, slippage, trade fills, and HMM state transitions to `telemetry.db`.
"""

import sqlite3
import os
import logging
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.time_utils import now_ist_iso

log = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "telemetry.db")

class TelemetryDB:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._create_tables()

    def _create_tables(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    instrument TEXT,
                    action TEXT,
                    qty REAL,
                    price REAL,
                    slippage REAL,
                    latency_ms REAL,
                    hmm_state TEXT
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS hmm_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    instrument TEXT,
                    state TEXT,
                    likelihood REAL
                )
            """)

    def log_execution(self, instrument: str, action: str, qty: float, price: float, 
                      slippage: float = 0.0, latency_ms: float = 0.0, hmm_state: str = "UNKNOWN"):
        try:
            with self.conn:
                self.conn.execute(
                    """INSERT INTO executions (timestamp, instrument, action, qty, price, slippage, latency_ms, hmm_state) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (now_ist_iso(), instrument, action, qty, price, slippage, latency_ms, hmm_state)
                )
            log.debug(f"[Telemetry] Logged execution for {instrument} ({action})")
        except Exception as e:
            log.error(f"[Telemetry] Error logging execution: {e}")

    def log_hmm_state(self, instrument: str, state: str, likelihood: float):
        try:
            with self.conn:
                self.conn.execute(
                    """INSERT INTO hmm_states (timestamp, instrument, state, likelihood) 
                       VALUES (?, ?, ?, ?)""",
                    (now_ist_iso(), instrument, state, likelihood)
                )
        except Exception as e:
            log.error(f"[Telemetry] Error logging HMM state: {e}")

# Singleton instance
telemetry = TelemetryDB()
