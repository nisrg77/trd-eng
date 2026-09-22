"""
brain/models/lstm_model.py — [M3] LSTM (Temporal Sequence)

Architecture:
  • 2-layer LSTM with dropout regularisation
  • Input  : sequence of (seq_len, n_features) normalised feature windows
  • Output : single scalar via tanh → ∈ [-1, +1]
  • Target : next-bar sign of log-return
  • Weights saved/loaded as .keras / .h5
"""

from __future__ import annotations

import os
import logging
import numpy as np
import pandas as pd

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
import config

log = logging.getLogger(__name__)

_WEIGHT_FILE = os.path.join(config.MODEL_WEIGHTS_DIR, "lstm_model.keras")

# Deferred import to avoid TF startup cost when not needed
_tf_loaded = False
_keras = None


def _get_keras():
    global _tf_loaded, _keras
    if not _tf_loaded:
        import tensorflow as tf
        tf.get_logger().setLevel("ERROR")
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
        _keras = tf.keras
        _tf_loaded = True
    return _keras


def _make_labels(close: pd.Series) -> np.ndarray:
    log_ret = np.log(close / close.shift(1)).shift(-1)
    return np.sign(log_ret.fillna(0.0)).values.astype(np.float32)


def _build_model(seq_len: int, n_features: int):
    keras = _get_keras()
    model = keras.Sequential([
        keras.layers.Input(shape=(seq_len, n_features)),
        keras.layers.LSTM(
            config.LSTM_UNITS,
            return_sequences=True,
            dropout=config.LSTM_DROPOUT,
            recurrent_dropout=0.0,
        ),
        keras.layers.LSTM(
            config.LSTM_UNITS // 2,
            return_sequences=False,
            dropout=config.LSTM_DROPOUT,
        ),
        keras.layers.Dense(32, activation="relu"),
        keras.layers.Dropout(config.LSTM_DROPOUT),
        keras.layers.Dense(1, activation="tanh"),
    ])
    model.compile(optimizer="adam", loss="mse")
    return model


class LSTMModel:
    """
    Keras LSTM wrapper with walk-forward retraining.
    On cold-start (no saved weights), trains from scratch.
    """

    def __init__(self) -> None:
        self.model = None
        self.is_trained = False
        self._bar_counter = 0
        self.seq_len = config.LSTM_SEQ_LEN
        self.n_features = 4  # frac_diff, garch_vol, obi, rsi_14
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _save(self) -> None:
        os.makedirs(config.MODEL_WEIGHTS_DIR, exist_ok=True)
        self.model.save(_WEIGHT_FILE)
        log.debug("LSTM weights saved → %s", _WEIGHT_FILE)

    def _load(self) -> None:
        if os.path.exists(_WEIGHT_FILE):
            try:
                keras = _get_keras()
                self.model = keras.models.load_model(_WEIGHT_FILE)
                self.is_trained = True
                log.info("LSTM weights loaded from %s", _WEIGHT_FILE)
            except Exception as exc:
                log.warning("Could not load LSTM weights: %s", exc)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _build_sequences(
        self, X: np.ndarray, y: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Build (X_seq, y_seq) from feature matrix and label vector.
        Each X_seq[i] is a (seq_len, n_features) window.
        Each y_seq[i] is the label for the bar *after* that window ends.
        """
        n = len(X)
        X_seq, y_seq = [], []
        for i in range(self.seq_len, n):
            X_seq.append(X[i - self.seq_len: i])
            y_seq.append(y[i])
        return np.array(X_seq, dtype=np.float32), np.array(y_seq, dtype=np.float32)

    # ── training ─────────────────────────────────────────────────────────────

    def train(self, X: np.ndarray, close: pd.Series) -> None:
        lookback = config.TRAINING_LOOKBACK_BARS
        X = X[-lookback:]
        close = close.iloc[-lookback:]

        y = _make_labels(close)

        X_seq, y_seq = self._build_sequences(X, y)
        if len(X_seq) < 10:
            log.warning("LSTM: insufficient sequences (%d)", len(X_seq))
            return

        if self.model is None:
            self.model = _build_model(self.seq_len, self.n_features)

        keras = _get_keras()
        callbacks = [
            keras.callbacks.EarlyStopping(
                monitor="loss", patience=3, restore_best_weights=True
            )
        ]
        self.model.fit(
            X_seq, y_seq,
            epochs=config.LSTM_EPOCHS,
            batch_size=config.LSTM_BATCH_SIZE,
            verbose=0,
            callbacks=callbacks,
        )
        self.is_trained = True
        self._save()
        log.info("LSTM trained on %d sequences (seq_len=%d)", len(X_seq), self.seq_len)

    def maybe_retrain(self, X: np.ndarray, close: pd.Series) -> None:
        self._bar_counter += 1
        if (not self.is_trained) or (
            self._bar_counter % config.WALK_FORWARD_RETRAIN_EVERY == 0
        ):
            self.train(X, close)

    # ── inference ─────────────────────────────────────────────────────────────

    def predict(self, X: np.ndarray) -> float:
        """
        Predict from the full feature matrix; uses the last seq_len rows.

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
