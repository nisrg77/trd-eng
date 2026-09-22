"""
brain/models/ridge_model.py — [M1] Ridge Regression (Statistical Baseline)

Walk-forward rolling approach:
  • Trained on the last TRAINING_LOOKBACK_BARS bars
  • Target  : next-bar sign of log-return  → mapped to [-1, +1]
  • Output  : scalar prediction ∈ [-1, +1]
  • Weights saved/loaded via joblib
"""

from __future__ import annotations

import os
import logging
import numpy as np
import pandas as pd
import joblib

from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
import config

log = logging.getLogger(__name__)

_WEIGHT_FILE = os.path.join(config.MODEL_WEIGHTS_DIR, "ridge_model.joblib")


def _make_labels(close: pd.Series) -> np.ndarray:
    """
    Target = sign of next-bar log-return, in [-1, +1].
    Last bar has no future; we shift by -1 and drop the tail.
    """
    log_ret = np.log(close / close.shift(1)).shift(-1)  # next-bar return
    return np.sign(log_ret.fillna(0.0)).values.astype(np.float32)


class RidgeModel:
    """
    Scikit-learn Ridge Regression wrapper with walk-forward retraining.
    """

    def __init__(self) -> None:
        self.model = Ridge(alpha=config.RIDGE_ALPHA)
        self.scaler = StandardScaler()
        self.is_trained = False
        self._bar_counter = 0
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _save(self) -> None:
        os.makedirs(config.MODEL_WEIGHTS_DIR, exist_ok=True)
        joblib.dump({"model": self.model, "scaler": self.scaler}, _WEIGHT_FILE)
        log.debug("Ridge weights saved → %s", _WEIGHT_FILE)

    def _load(self) -> None:
        if os.path.exists(_WEIGHT_FILE):
            data = joblib.load(_WEIGHT_FILE)
            self.model = data["model"]
            self.scaler = data["scaler"]
            self.is_trained = True
            log.info("Ridge weights loaded from %s", _WEIGHT_FILE)

    # ── training ─────────────────────────────────────────────────────────────

    def train(self, X: np.ndarray, close: pd.Series) -> None:
        """
        Train on the last TRAINING_LOOKBACK_BARS bars.

        Parameters
        ----------
        X     : (n_bars, n_features)  normalised feature matrix
        close : pd.Series             raw close price series (same length as X)
        """
        lookback = config.TRAINING_LOOKBACK_BARS
        X = X[-lookback:]
        close = close.iloc[-lookback:]

        y = _make_labels(close)[:-1]  # drop last (no future label)
        Xt = X[:-1]                   # align

        if len(Xt) < 10:
            log.warning("Ridge: insufficient training data (%d rows)", len(Xt))
            return

        Xt_scaled = self.scaler.fit_transform(Xt)
        self.model.fit(Xt_scaled, y)
        self.is_trained = True
        self._save()
        log.info("Ridge trained on %d samples", len(Xt))

    def maybe_retrain(self, X: np.ndarray, close: pd.Series) -> None:
        """Retrain every WALK_FORWARD_RETRAIN_EVERY calls, or if not trained."""
        self._bar_counter += 1
        if (not self.is_trained) or (
            self._bar_counter % config.WALK_FORWARD_RETRAIN_EVERY == 0
        ):
            self.train(X, close)

    # ── inference ─────────────────────────────────────────────────────────────

    def predict(self, x_latest: np.ndarray) -> float:
        """
        Predict direction for the latest bar.

        Returns
        -------
        float ∈ [-1, +1]
        """
        if not self.is_trained:
            log.warning("Ridge not trained — returning 0.0")
            return 0.0
        x_scaled = self.scaler.transform(x_latest)
        raw = self.model.predict(x_scaled)[0]
        return float(np.clip(raw, -1.0, 1.0))
