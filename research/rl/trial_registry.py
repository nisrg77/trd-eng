"""
research/rl/trial_registry.py — Persistent Multi-Testing Trial Registry for DSR

Tracks every candidate evaluation across RL seeds, alpha mining expressions,
and Optuna hyperparameter sweeps to prevent data-snooping bias and maintain
accurate Deflated Sharpe Ratio (Bailey & López de Prado, 2014) significance.
"""

from __future__ import annotations
import os
import json
import time
import threading
import logging
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional

log = logging.getLogger(__name__)

DEFAULT_REGISTRY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "runs",
    "trial_registry.jsonl"
)


@dataclass
class TrialRecord:
    config_hash: str
    fold: Any
    seed: int
    sharpe: float
    timestamp: float
    source: str  # "rl_seed" | "alpha_mining" | "hparam_sweep"
    extra_meta: Optional[Dict[str, Any]] = None


class TrialRegistry:
    """
    Thread-safe, append-only persistent registry of all candidate trials.
    """

    def __init__(self, filepath: Optional[str] = None) -> None:
        self.filepath = filepath or DEFAULT_REGISTRY_PATH
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(self.filepath)), exist_ok=True)

    def record_trial(
        self,
        config_hash: str,
        fold: Any,
        seed: int,
        sharpe: float,
        source: str = "rl_seed",
        extra_meta: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None
    ) -> TrialRecord:
        """
        Appends a candidate evaluation trial to the persistent JSONL registry.
        """
        ts = timestamp or time.time()
        record = TrialRecord(
            config_hash=str(config_hash),
            fold=fold,
            seed=int(seed),
            sharpe=float(sharpe),
            timestamp=ts,
            source=str(source),
            extra_meta=extra_meta or {}
        )
        line = json.dumps(asdict(record))
        with self._lock:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        return record

    def get_all_trials(self, source: Optional[str] = None) -> List[Dict[str, Any]]:
        """Reads all trial records from disk, optionally filtered by source."""
        if not os.path.exists(self.filepath):
            return []
        trials = []
        with self._lock:
            with open(self.filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if source is None or record.get("source") == source:
                            trials.append(record)
                    except json.JSONDecodeError:
                        continue
        return trials

    def get_trial_count(self, source: Optional[str] = None) -> int:
        """Returns the number of recorded trials."""
        return len(self.get_all_trials(source=source))

    def get_all_sharpes(self, source: Optional[str] = None) -> List[float]:
        """Returns all recorded Sharpe ratios across historical trials."""
        trials = self.get_all_trials(source=source)
        return [float(t["sharpe"]) for t in trials if "sharpe" in t and t["sharpe"] is not None]


# Global singleton instance
trial_registry = TrialRegistry()
