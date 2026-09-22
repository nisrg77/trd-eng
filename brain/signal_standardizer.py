"""
brain/signal_standardizer.py — [SS] Signal Standardizer

Converts the raw aggregation result into the canonical signal packet
that is published to the Message Broker.

Output schema (matches datatr.txt §2):
{
  "signal_id"          : str    (sig_<8-char hex>)
  "timestamp_generated": float  (UTC unix epoch)
  "instrument"         : str
  "direction_magnitude": float  ∈ [-1.0, +1.0]
  "confidence_score"   : float  ∈ [ 0.0,  1.0]
  "regime_flag"        : str
  "latency_ms"         : float
  "per_model"          : dict   (ridge/xgb/lstm individual signals)
  "weights_used"       : dict
  "ohlcv"              : dict   (latest bar OHLCV for the dashboard)
}
"""

from __future__ import annotations

import uuid
import time
import logging
import math

log = logging.getLogger(__name__)


def _compute_confidence(
    ridge: float,
    xgb: float,
    lstm: float,
    blended: float,
) -> float:
    """
    Confidence = agreement-weighted signal strength.

    1. Agreement score: how well the three signals agree in direction.
       All same sign → 1.0 ; two agree → 0.67 ; all disagree → 0.33
    2. Magnitude factor: |blended| normalised to [0, 1].
    3. confidence = agreement × magnitude, clipped to [0, 1].
    """
    signs = [math.copysign(1, s) if s != 0 else 0 for s in (ridge, xgb, lstm)]
    positive = sum(1 for s in signs if s > 0)
    negative = sum(1 for s in signs if s < 0)
    majority = max(positive, negative)
    agreement = majority / 3.0  # ∈ [0.33, 1.0]

    magnitude = abs(blended)    # ∈ [0, 1]

    confidence = agreement * (0.4 + 0.6 * magnitude)  # bias towards non-zero
    return round(float(min(max(confidence, 0.0), 1.0)), 4)


class SignalStandardizer:
    """
    Produces the canonical TEDENG signal packet from aggregation results.
    """

    def standardize(
        self,
        instrument: str,
        aggregation: dict,
        feature_payload: dict,
        pipeline_start_ts: float,
    ) -> dict:
        """
        Parameters
        ----------
        instrument       : str   ticker symbol
        aggregation      : dict  output of MetaAggregator.aggregate()
        feature_payload  : dict  original DP payload (for ohlcv)
        pipeline_start_ts: float unix timestamp when the pipeline started (for latency)

        Returns
        -------
        Canonical signal packet dict.
        """
        now = time.time()
        latency_ms = round((now - pipeline_start_ts) * 1000, 2)

        blended = aggregation["blended_signal"]
        per_model = aggregation["per_model"]

        confidence = _compute_confidence(
            ridge=per_model["ridge"],
            xgb=per_model["xgb"],
            lstm=per_model["lstm"],
            blended=blended,
        )

        signal_id = f"sig_{uuid.uuid4().hex[:8]}"

        packet = {
            "signal_id":           signal_id,
            "timestamp_generated": round(now, 3),
            "instrument":          instrument,
            "direction_magnitude": round(blended, 4),
            "confidence_score":    confidence,
            "regime_flag":         aggregation["regime_flag"],
            "latency_ms":          latency_ms,
            "per_model":           per_model,
            "weights_used":        aggregation["weights_used"],
            "ohlcv":               feature_payload.get("ohlcv", {}),
        }

        log.info(
            "SS  [%s]  signal=%s  dir=%.4f  conf=%.3f  regime=%s  latency=%.1fms",
            instrument,
            signal_id,
            blended,
            confidence,
            aggregation["regime_flag"],
            latency_ms,
        )
        return packet
