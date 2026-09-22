"""
brain/models/rf_model.py — [M4] Random Forest (US Stock Futures)

Walk-forward rolling approach:
  • Trained on the last TRAINING_LOOKBACK_BARS bars
  • Target  : next-bar sign of log-return → [-1, +1]
  • Output  : scalar prediction ∈ [-1, +1]
  • Weights saved/loaded via joblib
"""

from __future__ import annotations

import os
import logging
import numpy as np
import pandas as pd
import joblib

from sklearn.ensemble import RandomForestRegressor

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
import config

log = logging.getLogger(__name__)

_WEIGHT_FILE = os.path.join(config.MODEL_WEIGHTS_DIR, "rf_model.joblib")

FEATURE_NAMES = ["frac_diff", "garch_vol", "obi", "rsi_14"]


def _make_labels(close: pd.Series) -> np.ndarray:
    log_ret = np.log(close / close.shift(1)).shift(-1)
    return np.sign(log_ret.fillna(0.0)).values.astype(np.float32)


class RFModel:
    """
    Random Forest regressor wrapper with walk-forward retraining.
    Specifically designed for the US Stock Futures pipeline.
    Logs feature importances after each training run.
    """

    def __init__(self) -> None:
        self.model = RandomForestRegressor(
            n_estimators=100,
            max_depth=5,
            random_state=42,
            n_jobs=-1
        )
        self.is_trained = False
        self._bar_counter = 0
        self.feature_importances: dict[str, float] = {}
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _save(self) -> None:
        os.makedirs(config.MODEL_WEIGHTS_DIR, exist_ok=True)
        joblib.dump({"model": self.model, "fi": self.feature_importances}, _WEIGHT_FILE)
        log.debug("RF weights saved → %s", _WEIGHT_FILE)

    def _load(self) -> None:
        if os.path.exists(_WEIGHT_FILE):
            data = joblib.load(_WEIGHT_FILE)
            self.model = data["model"]
            self.feature_importances = data.get("fi", {})
            self.is_trained = True
            log.info("RF weights loaded from %s", _WEIGHT_FILE)

    # ── training ─────────────────────────────────────────────────────────────

    def train(self, X: np.ndarray, close: pd.Series) -> None:
        lookback = config.TRAINING_LOOKBACK_BARS
        X = X[-lookback:]
        close = close.iloc[-lookback:]

        y = _make_labels(close)[:-1]
        Xt = X[:-1]

        if len(Xt) < 10:
            log.warning("RF: insufficient training data (%d rows)", len(Xt))
            return

        self.model.fit(Xt, y)
        self.is_trained = True

        # Log feature importances
        imp = self.model.feature_importances_
        self.feature_importances = {
            FEATURE_NAMES[i]: round(float(imp[i]), 4)
            for i in range(min(len(FEATURE_NAMES), len(imp)))
        }
        log.info("RF trained on %d samples | importances: %s", len(Xt), self.feature_importances)
        self._save()

    def maybe_retrain(self, X: np.ndarray, close: pd.Series) -> None:
        self._bar_counter += 1
        if (not self.is_trained) or (
            self._bar_counter % config.WALK_FORWARD_RETRAIN_EVERY == 0
        ):
            self.train(X, close)

    # ── inference ─────────────────────────────────────────────────────────────

    def predict(self, x_latest: np.ndarray) -> float:
        if not self.is_trained:
            log.warning("RF not trained — returning 0.0")
            return 0.0
        # reshape if it's 1D
        if x_latest.ndim == 1:
            x_latest = x_latest.reshape(1, -1)
        raw = self.model.predict(x_latest)[0]
        return float(np.clip(raw, -1.0, 1.0))
