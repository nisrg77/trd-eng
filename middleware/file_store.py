"""
middleware/file_store.py — File-based Signal Store

Simple JSON file store so the dashboard can read signals
without needing Redis or sharing a process with the backend.

Backend writes  →  signals_store.json
Dashboard reads ←  signals_store.json
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

_STORE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "signals_store.json")
_EXEC_STORE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "execution_store.json")
_lock = threading.Lock()


def write_signal(signal: dict) -> None:
    """Append a signal to the store, keeping the last 500 per instrument."""
    with _lock:
        store = _read_raw()
        instr = signal.get("instrument", "UNKNOWN")
        if instr not in store:
            store[instr] = []
        store[instr].append(signal)
        if len(store[instr]) > 500:
            store[instr] = store[instr][-500:]
        with open(_STORE_PATH, "w") as f:
            json.dump(store, f)


def read_all() -> dict[str, list[dict]]:
    """Return all signals grouped by instrument."""
    with _lock:
        return _read_raw()


def read_latest(instrument: str) -> dict | None:
    """Return the latest signal for a given instrument."""
    store = read_all()
    sigs = store.get(instrument, [])
    return sigs[-1] if sigs else None


def _read_raw() -> dict:
    if not os.path.exists(_STORE_PATH):
        return {}
    try:
        with open(_STORE_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

# ─────────────────────────────────────────────────────────────────────────────
# EXECUTION LOGS
# ─────────────────────────────────────────────────────────────────────────────

def write_execution_log(log_entry: dict) -> None:
    """Append an execution log to the execution store."""
    with _lock:
        store = _read_exec_raw()
        store.append(log_entry)
        if len(store) > 500:
            store = store[-500:]
        with open(_EXEC_STORE_PATH, "w") as f:
            json.dump(store, f)

def read_all_executions() -> list[dict]:
    """Return all execution logs."""
    with _lock:
        return _read_exec_raw()

def _read_exec_raw() -> list:
    if not os.path.exists(_EXEC_STORE_PATH):
        return []
    try:
        with open(_EXEC_STORE_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return []
