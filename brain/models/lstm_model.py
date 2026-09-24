"""
brain/models/lstm_model.py — [M3] LSTM (Recurrent Neural Network)

Walk-forward rolling approach:
  • Sequential window of sequence length bars (default 30)
  • Target  : next-bar sign of log-return → [-1, +1]
  • Output  : scalar prediction ∈ [-1, +1]
"""

from __future__ import annotations

import os
import logging
import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
import config

log = logging.getLogger(__name__)

_WEIGHT_FILE = os.path.join(config.MODEL_WEIGHTS_DIR, "lstm_model.keras")


def next_bar_labels(close: pd.Series) -> np.ndarray:
    """Target = sign of next-bar log-return, in [-1, +1]."""
    log_ret = np.log(close / close.shift(1)).shift(-1)
    return np.sign(log_ret.fillna(0.0)).values.astype(np.float32)


def build_sequence_samples(X: np.ndarray, y: np.ndarray, seq_len: int) -> tuple[np.ndarray, np.ndarray]:
    """Prepares rolling sequential windows for LSTM training."""
    X_seq, y_seq = [], []
    for i in range(seq_len, len(X) - 1):
        X_seq.append(X[i - seq_len:i])
        y_seq.append(y[i])
    if not X_seq:
        return np.empty((0, seq_len, X.shape[1]), dtype=np.float32), np.empty((0,), dtype=np.float32)
    return np.array(X_seq, dtype=np.float32), np.array(y_seq, dtype=np.float32)


class LSTMModel:
    """
    Keras LSTM model with walk-forward sequence training.
    """

    def __init__(self, seq_len: int = 30) -> None:
        self.seq_len = seq_len
        self.units = config.LSTM_UNITS
        self.dropout = config.LSTM_DROPOUT
        self.epochs = config.LSTM_EPOCHS
        self.batch_size = config.LSTM_BATCH_SIZE
        self.model = None
        self.is_trained = False
        self._bar_counter = 0
        self._load()

    def _build_model(self, n_features: int) -> tf.keras.Model:
        model = Sequential([
            LSTM(self.units, return_sequences=False, input_shape=(self.seq_len, n_features)),
            Dropout(self.dropout),
            Dense(32, activation="relu"),
            Dense(1, activation="tanh")
        ])
        model.compile(optimizer="adam", loss="mse")
        return model

    def _save(self) -> None:
        if self.model is not None and self.is_trained:
            os.makedirs(config.MODEL_WEIGHTS_DIR, exist_ok=True)
            try:
                self.model.save(_WEIGHT_FILE)
            except Exception as e:
                log.warning("Could not save LSTM model: %s", e)

    def _load(self) -> None:
        if os.path.exists(_WEIGHT_FILE):
            try:
                self.model = load_model(_WEIGHT_FILE)
                self.is_trained = True
                log.info("Loaded LSTM weights from %s", _WEIGHT_FILE)
            except Exception as e:
                log.warning("Failed to load LSTM weights: %s", e)

    def train(self, X: np.ndarray, close: pd.Series) -> None:
        n_bars, n_features = X.shape
        if n_bars < self.seq_len + 10:
            log.warning("LSTM: not enough data to train (%d bars)", n_bars)
            return

        y_all = next_bar_labels(close)
        X_seq, y_seq = build_sequence_samples(X, y_all, self.seq_len)

        if len(X_seq) == 0:
            return

        if self.model is None or not self.is_trained:
            self.model = self._build_model(n_features)

        self.model.fit(
            X_seq, y_seq,
            epochs=self.epochs,
            batch_size=self.batch_size,
            verbose=0,
            shuffle=False
        )
        self.is_trained = True
        self._save()

    def predict(self, X: np.ndarray) -> float:
        """
        Parameters
        ----------
        X : (n_bars, n_features)

        Returns
        -------
        float ∈ [-1, +1]
        """
        if not self.is_trained or self.model is None:
            log.warning("LSTM not trained — returning 0.0")
            return 0.0

        if len(X) < self.seq_len:
            log.warning("LSTM: not enough bars for inference (%d < %d)", len(X), self.seq_len)
            return 0.0

        x_seq = X[-self.seq_len:][np.newaxis, :, :]  # (1, seq_len, n_features)
        raw = self.model.predict(x_seq, verbose=0)[0][0]
        return float(np.clip(raw, -1.0, 1.0))
