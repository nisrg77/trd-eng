"""
brain/meta_aggregator.py — [MA] Regime-Based Meta-Aggregator

Responsibilities:
  • Detect the current market regime from the garch_vol feature
  • Look up the per-regime weight table from config.py
  • Blend the three model predictions into a single aggregated signal

Regimes:
  low_volatility   → garch_vol < REGIME_VOL_THRESHOLD_LOW
  high_volatility  → garch_vol > REGIME_VOL_THRESHOLD_HIGH
  trending         → otherwise

Output:
  {
    "blended_signal" : float ∈ [-1, +1],
    "regime_flag"    : str,
    "per_model"      : {"ridge": float, "xgb": float, "lstm": float},
    "weights_used"   : {"ridge": float, "xgb": float, "lstm": float},
  }
"""

from __future__ import annotations

import logging
import numpy as np

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from core.patch_helpers import annualized_to_daily_vol

log = logging.getLogger(__name__)


def _detect_regime(garch_vol: float, trend_metric: float = 0.0, thresholds=None) -> str:
    lo, hi = thresholds or (config.REGIME_VOL_THRESHOLD_LOW, config.REGIME_VOL_THRESHOLD_HIGH)
    if garch_vol > hi:            return "high_volatility"
    elif garch_vol < lo:          return "low_volatility"
    elif trend_metric > 0.005:    return "trending_up"
    else:                         return "trending"


class MetaAggregator:
    """
    Blends ridge / xgb / lstm signals using regime-conditional weights.
    """

    def __init__(self) -> None:
        self.weight_table = config.REGIME_WEIGHTS
        log.info(
            "MetaAggregator initialised | regimes: %s",
            list(self.weight_table.keys()),
        )

    def aggregate(
        self,
        ridge_signal: float,
        xgb_signal: float,
        lstm_signal: float,
        garch_vol: float,
        trend_metric: float = 0.0,
        instrument: str = "",
        obi_rho: float = 0.0,
        vol_thresholds=None,
        vol_is_annualized: bool = False,
    ) -> dict:
        """
        Parameters
        ----------
        ridge_signal : float ∈ [-1, +1]
        xgb_signal   : float ∈ [-1, +1]
        lstm_signal  : float ∈ [-1, +1]
        garch_vol    : float  (latest annualised vol from DP payload)
        trend_metric : float  (optional directional trend/drift score)
        instrument   : str    (optional instrument identifier)
        obi_rho      : float  (optional order book imbalance)

        Returns
        -------
        dict with keys: blended_signal, regime_flag, per_model, weights_used
        (S_composite is untouched at this stage; IFF gate is applied downstream)
        """
        if vol_is_annualized:
            garch_vol = annualized_to_daily_vol(garch_vol)      # `garch_vol` is now DAILY vol by contract
        regime = _detect_regime(garch_vol, trend_metric, vol_thresholds)
        weights = self.weight_table.get(regime, self.weight_table.get("trending", {"ridge": 0.34, "xgb": 0.33, "lstm": 0.33}))

        blended = (
            weights["ridge"] * ridge_signal
            + weights["xgb"]   * xgb_signal
            + weights["lstm"]  * lstm_signal
        )
        blended = float(np.clip(blended, -1.0, 1.0))

        result = {
            "blended_signal": round(blended, 6),
            "regime_flag": regime,
            "per_model": {
                "ridge": round(ridge_signal, 6),
                "xgb":   round(xgb_signal, 6),
                "lstm":  round(lstm_signal, 6),
            },
            "weights_used": weights,
        }

        log.debug(
            "MA  regime=%-18s  ridge=%.3f  xgb=%.3f  lstm=%.3f  blended=%.3f",
            regime, ridge_signal, xgb_signal, lstm_signal, blended,
        )
        return result

