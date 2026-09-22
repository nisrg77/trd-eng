"""
brain/preprocessor.py — [PP] Feature Pre-processor

Responsibilities:
  • Rolling Z-score normalisation per feature column
  • Forward-fill / mean imputation for NaN values
  • Reconstruct numpy arrays ready for model ingestion

Input  : feature payload dict from DP (including _feature_history)
Output : dict of normalised feature arrays + scalar for the latest bar
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Tuple

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config


FEATURE_KEYS = ["frac_diff", "garch_vol", "obi", "rsi_14"]


def _impute(series: pd.Series, strategy: str = config.IMPUTE_STRATEGY) -> pd.Series:
    """Fill NaN values according to the configured strategy."""
    if strategy == "ffill":
        return series.ffill().bfill()
    elif strategy == "mean":
        return series.fillna(series.mean())
    else:
        return series.fillna(0.0)


def _rolling_zscore(series: pd.Series, window: int = config.ZSCORE_WINDOW) -> pd.Series:
    """
    Compute rolling Z-score:
        z_t = (x_t - rolling_mean_t) / rolling_std_t
    Clips to [-5, +5] to guard against extreme outliers.
    """
    mu = series.rolling(window=window, min_periods=1).mean()
    sigma = series.rolling(window=window, min_periods=1).std().replace(0, np.nan)
    z = (series - mu) / sigma
    return z.clip(-5.0, 5.0).fillna(0.0)


class FeaturePreprocessor:
    """
    Normalises feature history arrays from a DP payload.

    Usage:
        pp = FeaturePreprocessor()
        X, x_latest = pp.transform(dp_payload)
        # X         : (n_bars, n_features) float32 array — full history
        # x_latest  : (1, n_features) float32 — the most recent bar (for inference)
    """

    def __init__(self) -> None:
        self.window = config.ZSCORE_WINDOW
        self.strategy = config.IMPUTE_STRATEGY

    def transform(
        self, payload: dict
    ) -> Tuple[np.ndarray, np.ndarray, pd.Series]:
        """
        Parameters
        ----------
        payload : dict
            Feature payload from DataPipeline, must contain '_feature_history'.

        Returns
        -------
        X        : np.ndarray  shape (n_bars, n_features)  normalised history
        x_latest : np.ndarray  shape (1, n_features)       most recent bar
        close    : pd.Series   raw close price series (for label generation)
        """
        hist = payload.get("_feature_history", {})
        close_raw = payload.get("_close_history", [])

        frames: dict[str, pd.Series] = {}
        for key in FEATURE_KEYS:
            raw = hist.get(key, [])
            s = pd.Series(raw, dtype=float)
            s = _impute(s, self.strategy)
            s = _rolling_zscore(s, self.window)
            frames[key] = s

        df = pd.DataFrame(frames).astype(np.float32)

        # Drop leading rows that are still NaN after imputation
        df = df.dropna()

        X = df.values                          # (n_bars, 4)
        x_latest = X[-1:, :]                  # (1, 4)  ← inference point

        close = pd.Series(close_raw, dtype=float)
        # Align close to same length as X
        close = close.iloc[-len(X):]

        return X, x_latest, close

    def transform_sequence(
        self, X: np.ndarray, seq_len: int
    ) -> np.ndarray:
        """
        Reshape X into overlapping sequences for LSTM:
            shape (n_samples, seq_len, n_features)

        Only bars with a full seq_len lookback are included.
        """
        n, f = X.shape
        if n < seq_len:
            raise ValueError(
                f"Not enough bars ({n}) to form sequences of length {seq_len}"
            )
        samples = []
        for i in range(seq_len, n + 1):
            samples.append(X[i - seq_len: i])
        return np.array(samples, dtype=np.float32)  # (n_samples, seq_len, f)
