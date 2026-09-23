"""
alpha_overlay/iff.py — Composite Flow Score (S_flow)

Combines three microstructure/macro signals into a single scalar:

    S_flow = w_cot * Z_COT_norm + w_cvd * S_predictive + w_obi * rho(t)

Weights are loaded from config and differ by instrument class:
    Crypto   (proxy COT):  [w_cot=0.20, w_cvd=0.50, w_obi=0.30]
    Equities (direct COT): [w_cot=0.50, w_cvd=0.30, w_obi=0.20]

During Phase 1–4 cot_bias.get_cot_zscore() returns 0.0, so S_flow is
effectively driven by CVD divergence and OBI only.

Public API
----------
get_flow_score(symbol, obi_rho) -> float ∈ [-1.0, +1.0]
    Single entry-point consumed by meta_aggregator and engine.
"""

from __future__ import annotations

import logging
import numpy as np

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

from alpha_overlay.vap_cvd import get_predictive_signal
from alpha_overlay.cot_bias import get_cot_zscore

log = logging.getLogger(__name__)

# COT z-scores are typically in [-3, +3]; normalise to [-1, +1] for blending
_COT_NORM_CLIP = 3.0


def _get_weights(symbol: str) -> tuple[float, float, float]:
    """
    Returns (w_cot, w_cvd, w_obi) for the given instrument.
    Uses FLOW_SCORE_WEIGHTS_CRYPTO for crypto, FLOW_SCORE_WEIGHTS_EQUITIES otherwise.
    Falls back to hard-coded defaults if config keys are missing.
    """
    is_crypto = symbol in config.CRYPTO_INSTRUMENTS
    if is_crypto:
        weights = getattr(config, "FLOW_SCORE_WEIGHTS_CRYPTO", [0.20, 0.50, 0.30])
    else:
        weights = getattr(config, "FLOW_SCORE_WEIGHTS_EQUITIES", [0.50, 0.30, 0.20])

    if len(weights) != 3:
        log.warning("FLOW_SCORE_WEIGHTS for %s has wrong length; using defaults", symbol)
        weights = [0.20, 0.50, 0.30] if is_crypto else [0.50, 0.30, 0.20]

    return float(weights[0]), float(weights[1]), float(weights[2])


def get_flow_score(symbol: str, obi_rho: float) -> float:
    """
    Compute and return the composite institutional flow score S_flow.

    Parameters
    ----------
    symbol   : Instrument identifier (e.g. "BTC-USD", "AAPL")
    obi_rho  : Latest Order Book Imbalance rho ∈ [-1, +1] from the DP payload
               (key: "order_book_imbalance" in the features dict)

    Returns
    -------
    float ∈ [-1.0, +1.0]
        Positive → net bullish institutional pressure
        Negative → net bearish institutional pressure
    """
    w_cot, w_cvd, w_obi = _get_weights(symbol)

    # --- Component 1: COT z-score (normalised to [-1, +1]) ---
    raw_cot = get_cot_zscore(symbol)
    z_cot_norm = float(np.clip(raw_cot / _COT_NORM_CLIP, -1.0, 1.0))

    # --- Component 2: CVD predictive signal ---
    cvd_divergence = get_predictive_signal(symbol)   # already ∈ [-1, +1]

    # --- Component 3: Order Book Imbalance ---
    obi = float(np.clip(obi_rho, -1.0, 1.0))

    # --- Blend ---
    s_flow = w_cot * z_cot_norm + w_cvd * cvd_divergence + w_obi * obi
    s_flow = float(np.clip(s_flow, -1.0, 1.0))

    # Record flow tick timestamp for micro-buffer hold queue tracking
    _record_flow_tick(symbol, s_flow)

    log.debug(
        "IFF  %-10s  Z_COT=%.3f  CVD_div=%.3f  OBI=%.3f  "
        "weights=[%.2f,%.2f,%.2f]  S_flow=%.4f",
        symbol, z_cot_norm, cvd_divergence, obi,
        w_cot, w_cvd, w_obi, s_flow,
    )
    return s_flow



def apply_iff_gate(
    s_composite: float,
    symbol: str,
    obi_rho: float = 0.0,
) -> tuple[float, float, bool]:
    """
    Applies the IFF directional veto and soft-scaling gate to an untouched S_composite.
    Applied immediately after the Meta-Aggregator rather than inside it.

    Decision Rules:
    - Graduated threshold: Hard veto ONLY when ML direction directly opposes flow
      and |S_flow| > 0.5 (or config.IFF_VETO_THRESHOLD):
          gated_signal = 0.0
          iff_veto = True
    - Otherwise (aligned or neutral / non-extreme):
          gated_signal = S_composite * (1.0 + 0.5 * S_flow)
          iff_veto = False

    Parameters
    ----------
    s_composite : float ∈ [-1.0, +1.0] from MetaAggregator (untouched)
    symbol      : Instrument identifier (e.g. "BTC-USD", "AAPL")
    obi_rho     : Latest Order Book Imbalance ρ ∈ [-1.0, +1.0]

    Returns
    -------
    tuple of (gated_signal: float, flow_score: float, iff_veto: bool)
    """
    flow_score = get_flow_score(symbol, obi_rho)
    veto_threshold = getattr(config, "IFF_VETO_THRESHOLD", 0.5)

    # Record flow tick timestamp for micro-buffer dwell tracking
    _record_flow_tick(symbol, flow_score)

    opposing_long  = s_composite > 0 and flow_score < -veto_threshold
    opposing_short = s_composite < 0 and flow_score >  veto_threshold

    if opposing_long or opposing_short:
        log.info(
            "IFF GATE VETO  %-10s  S_composite=%.3f  S_flow=%.3f  (threshold=%.2f)",
            symbol, s_composite, flow_score, veto_threshold,
        )
        return 0.0, round(flow_score, 6), True

    # Graduated soft scaling: S_composite * (1 + 0.5 * S_flow)
    scale = 1.0 + 0.5 * flow_score
    gated = float(np.clip(s_composite * scale, -1.0, 1.0))
    return round(gated, 6), round(flow_score, 6), False


# ─────────────────────────────────────────────────────────────────────────────
# Micro-Buffer Hold Queue & Dwell-Time Preemption (Step 3 Future-Proofing)
# ─────────────────────────────────────────────────────────────────────────────

import time
from core.symbol_state import symbol_state_registry


def _record_flow_tick(symbol: str, flow_score: float) -> None:
    now = time.time()
    state = symbol_state_registry.get(symbol)
    state.record_flow_tick(now, flow_score)


def check_micro_buffer_veto(
    symbol: str,
    direction: str,  # "BUY" or "SELL"
    hold_ms: float = 50.0,
    dwell_ms: float = 10.0,
) -> tuple[bool, str]:
    """
    Evaluates micro-buffer hold queue for 10ms sustained opposing flow spikes during 50ms window.
    Returns (preempted: bool, reason: str).
    """
    if not getattr(config, "ENABLE_MICRO_BUFFER", True):
        return False, "Micro-buffer disabled"

    veto_thresh = getattr(config, "IFF_VETO_THRESHOLD", 0.5)
    state = symbol_state_registry.get(symbol)
    recent_ticks = state.get_recent_flow_ticks(hold_ms / 1000.0)
    
    if len(recent_ticks) < 2:
        return False, "Insufficient micro-ticks in hold window"

    # Check for sustained opposing flow spike >= dwell_ms duration
    opposing_duration = 0.0
    dwell_threshold_sec = dwell_ms / 1000.0

    for i in range(1, len(recent_ticks)):
        t_prev, f_prev = recent_ticks[i - 1]
        t_curr, f_curr = recent_ticks[i]
        dt = t_curr - t_prev

        is_prev_opposing = (direction == "BUY" and f_prev < -veto_thresh) or (direction == "SELL" and f_prev > veto_thresh)
        is_curr_opposing = (direction == "BUY" and f_curr < -veto_thresh) or (direction == "SELL" and f_curr > veto_thresh)

        if is_curr_opposing:
            if is_prev_opposing or dwell_threshold_sec == 0:
                opposing_duration += dt
            if opposing_duration >= dwell_threshold_sec:
                log.warning(
                    f"[MICRO-BUFFER] VETO PREEMPTION {symbol} ({direction}) — "
                    f"Opposing flow spike sustained for {opposing_duration * 1000:.1f}ms >= {dwell_ms:.1f}ms target"
                )
                return True, f"Preempted: Opposing flow spike sustained {opposing_duration * 1000:.1f}ms"
        else:
            opposing_duration = 0.0

    return False, "Passed micro-buffer evaluation"


def hold_and_evaluate_micro_buffer(
    symbol: str,
    direction: str,  # "BUY" or "SELL"
    hold_ms: float = 50.0,
    dwell_ms: float = 10.0,
) -> tuple[bool, str]:
    """
    Real-time monitoring hold queue:
    Polls in 5ms sub-intervals up to hold_ms. If an opposing flow spike occurs
    *during* the hold window, it preempts immediately before hold_ms elapses.
    """
    if not getattr(config, "ENABLE_MICRO_BUFFER", True):
        return False, "Micro-buffer disabled"

    if hold_ms <= 0:
        return check_micro_buffer_veto(symbol, direction, hold_ms=hold_ms, dwell_ms=dwell_ms)

    step_sec = 0.005  # 5ms sub-interval check
    elapsed = 0.0
    hold_sec = hold_ms / 1000.0

    while elapsed < hold_sec:
        preempted, reason = check_micro_buffer_veto(symbol, direction, hold_ms=hold_ms, dwell_ms=dwell_ms)
        if preempted:
            return True, reason
        time.sleep(step_sec)
        elapsed += step_sec

    return check_micro_buffer_veto(symbol, direction, hold_ms=hold_ms, dwell_ms=dwell_ms)


