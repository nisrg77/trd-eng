"""
brain/meta_labeling.py — Institutional Meta-Labeling & Triple Barrier Model

Implements Marcos López de Prado's Meta-Labeling framework:
1. Triple Barrier Method: Computes upper (Take Profit), lower (Stop Loss),
   and vertical (Max Time Horizon) barriers.
2. Binary Label: 1 if upper barrier is touched before lower/vertical, 0 otherwise.
3. Secondary Meta-Classifier: Predicts P(Win | Market Regime, Volatility, Microstructure).
4. Bet Sizing / Veto Filter: Authorizes primary strategy trades only when P(Win) >= threshold,
   and scales bet size proportional to meta-confidence.
"""

from __future__ import annotations
import math
import logging
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, Tuple
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from core.order_intent import OrderIntent, OrderSide, IntentType

log = logging.getLogger(__name__)


class TripleBarrierLabeler:
    """
    Labels historical trade signals using the Triple Barrier Method.
    """

    @staticmethod
    def generate_barriers(
        df: pd.DataFrame,
        signals: pd.Series,
        pt_multiplier: float = 1.5,
        sl_multiplier: float = 1.0,
        vol_col: str = "volatility_20",
        horizon_bars: int = 12
    ) -> pd.DataFrame:
        """
        Generates labels (1 = TP hit first, 0 = SL hit first or timed out)
        for every non-zero primary signal.
        """
        closes = df["close"].values
        n_bars = len(closes)
        
        # Volatility column or rolling std fallback
        if vol_col in df.columns:
            vols = df[vol_col].values
        else:
            vols = df["close"].pct_change().rolling(20).std().fillna(0.01).values

        labels = np.zeros(n_bars, dtype=int)
        ret_outcomes = np.zeros(n_bars, dtype=float)

        for i in range(n_bars - horizon_bars):
            sig = signals.iloc[i]
            if sig == 0 or np.isnan(sig):
                continue

            entry_px = closes[i]
            vol = max(0.002, vols[i])
            upper_barrier = entry_px * (1.0 + pt_multiplier * vol)
            lower_barrier = entry_px * (1.0 - sl_multiplier * vol)

            hit_tp = False
            hit_sl = False

            for j in range(1, horizon_bars + 1):
                cur_px = closes[i + j]
                if sig > 0:  # LONG
                    if cur_px >= upper_barrier:
                        hit_tp = True
                        break
                    elif cur_px <= lower_barrier:
                        hit_sl = True
                        break
                elif sig < 0:  # SHORT
                    short_tp = entry_px * (1.0 - pt_multiplier * vol)
                    short_sl = entry_px * (1.0 + sl_multiplier * vol)
                    if cur_px <= short_tp:
                        hit_tp = True
                        break
                    elif cur_px >= short_sl:
                        hit_sl = True
                        break

            labels[i] = 1 if hit_tp else 0
            exit_px = closes[i + j] if (hit_tp or hit_sl) else closes[i + horizon_bars]
            ret_outcomes[i] = (exit_px / entry_px - 1.0) * np.sign(sig)

        result_df = df.copy()
        result_df["meta_label"] = labels
        result_df["meta_return"] = ret_outcomes
        return result_df


class MetaLabelClassifier:
    """
    Secondary ML model that filters primary strategy signals and determines bet size.
    """

    def __init__(self, min_probability_threshold: float = 0.52) -> None:
        self.min_probability_threshold = min_probability_threshold
        self._model = GradientBoostingClassifier(
            n_estimators=50,
            max_depth=3,
            learning_rate=0.05,
            random_state=42
        )
        self.is_trained = False
        self.feature_names = [
            "volatility",
            "order_book_imbalance",
            "rsi_divergence",
            "volume_zscore",
            "conviction"
        ]

    def train(self, X: pd.DataFrame, y: pd.Series) -> None:
        """Trains the meta-model on historical feature states and triple-barrier outcomes."""
        valid_idx = ~(X.isna().any(axis=1) | y.isna())
        X_clean = X.loc[valid_idx]
        y_clean = y.loc[valid_idx]

        if len(y_clean) < 30 or len(y_clean.unique()) < 2:
            log.warning("[MetaLabeler] Insufficient diverse samples to train (%d). Skipping.", len(y_clean))
            return

        self._model.fit(X_clean[self.feature_names], y_clean)
        self.is_trained = True
        log.info("[MetaLabeler] Model trained successfully on %d samples.", len(y_clean))

    def predict_probability(self, features: Dict[str, float]) -> float:
        """Predicts probability P(Win = 1) for a given feature state."""
        if not self.is_trained:
            # Baseline uninformative prior when not yet trained
            return 0.55

        row = pd.DataFrame([{col: features.get(col, 0.0) for col in self.feature_names}])
        probs = self._model.predict_proba(row)[0]
        # Class 1 is Win
        return float(probs[1]) if len(probs) > 1 else float(probs[0])

    def evaluate_trade_intent(
        self,
        intent: OrderIntent,
        features: Dict[str, float]
    ) -> Tuple[bool, float, float]:
        """
        Meta-labeling trade filter:
        Returns:
            (should_execute: bool, win_prob: float, size_multiplier: float)
        """
        # Exits and cancels bypass the meta-model
        if intent.intent_type != IntentType.ENTRY:
            return True, 1.0, 1.0

        prob = self.predict_probability(features)

        if prob < self.min_probability_threshold:
            log.info(
                "[MetaLabeler] VETOED trade %s: Predicted P(Win)=%.2f < threshold=%.2f",
                intent.intent_id, prob, self.min_probability_threshold
            )
            return False, prob, 0.0

        # Kelly / continuous bet sizing multiplier: 0.5x to 1.5x based on edge
        edge = prob - self.min_probability_threshold
        size_multiplier = max(0.5, min(1.5, 1.0 + (edge * 2.0)))

        log.info(
            "[MetaLabeler] APPROVED trade %s: P(Win)=%.2f, Size Multiplier=%.2fx",
            intent.intent_id, prob, size_multiplier
        )
        return True, prob, round(size_multiplier, 2)


# Global meta-labeler instance
meta_labeler = MetaLabelClassifier()
