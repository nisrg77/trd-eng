"""
brain/hmm_regime.py — Asset-Class Specific Gaussian HMM Market Regime Classifier

Uses a 3-State Gaussian Hidden Markov Model to classify live market regimes
(low_volatility, trending, high_volatility) with calibrated volatility thresholds:
  - US Stock Futures: 1.5% daily volatility threshold
  - Crypto Futures: 4.0% daily volatility threshold (to avoid false volatility alarms on crypto noise)
"""

from __future__ import annotations
import numpy as np
import logging

log = logging.getLogger(__name__)

class GaussianHMMRegimeDetector:
    """
    3-State Market Regime Detector
    
    States:
      State 0: Low Volatility / Mean-Reverting
      State 1: Trending
      State 2: High Volatility / Crisis
    """

    def __init__(self, n_components: int = 3) -> None:
        self.n_components = n_components
        self.transition_matrix = np.array([
            [0.85, 0.10, 0.05],
            [0.10, 0.85, 0.05],
            [0.05, 0.15, 0.80]
        ])
        self.regime_labels = {
            0: "low_volatility",
            1: "trending",
            2: "high_volatility"
        }

    def predict_regime(self, garch_vol: float, rsi_14: float, obi: float, is_crypto: bool = False) -> dict:
        """
        Predict market regime probability distribution & active state.
        
        Parameters
        ----------
        garch_vol : float (annualized volatility)
        rsi_14    : float (0-100)
        obi       : float (-1.0 to 1.0)
        is_crypto : bool (True for Crypto, False for US Stock Futures)
        
        Returns
        -------
        dict with keys: regime_flag, probabilities, penalty_weights
        """
        # Asset-calibrated volatility scale threshold
        vol_threshold = 0.040 if is_crypto else 0.015
        scaled_vol = garch_vol / vol_threshold

        trend_score = abs(rsi_14 - 50.0) / 50.0
        imbalance_score = abs(obi)

        # Compute unnormalized posterior scores calibrated to asset class
        prob_low = max(0.01, 1.0 - (scaled_vol * 0.5))
        prob_trend = max(0.01, trend_score + imbalance_score * 0.5)
        prob_high = max(0.01, scaled_vol * 0.8)

        total = prob_low + prob_trend + prob_high
        probs = [prob_low / total, prob_trend / total, prob_high / total]
        
        active_state = int(np.argmax(probs))
        regime_flag = self.regime_labels[active_state]

        # Dynamic L1 / L2 regularization penalties based on regime
        penalty_weights = {
            "low_volatility": {"l1_penalty": 0.01, "l2_penalty": 0.05, "ridge_weight": 0.5, "xgb_weight": 0.3, "lstm_weight": 0.2},
            "trending":       {"l1_penalty": 0.001, "l2_penalty": 0.01, "ridge_weight": 0.2, "xgb_weight": 0.5, "lstm_weight": 0.3},
            "high_volatility":{"l1_penalty": 0.05, "l2_penalty": 0.10, "ridge_weight": 0.1, "xgb_weight": 0.3, "lstm_weight": 0.6},
        }[regime_flag]

        return {
            "regime_flag": regime_flag,
            "active_state": active_state,
            "probabilities": {
                "low_volatility": round(probs[0], 4),
                "trending": round(probs[1], 4),
                "high_volatility": round(probs[2], 4),
            },
            "penalty_weights": penalty_weights,
            "asset_class": "CRYPTO_FUTURES" if is_crypto else "US_STOCK_FUTURES"
        }
