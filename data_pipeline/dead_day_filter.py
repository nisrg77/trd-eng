"""
data_pipeline/dead_day_filter.py — Dead-Day Detector & Composite Conviction Calculator

Evaluates market state to produce:
1. is_dead_day (bool): True if day exhibits compressed range (<60% ATR) or low volume chop.
2. dead_day_reason (str): Diagnostic reason string.
3. raw_conviction (float): Base conviction from ML confidence, IFF flow alignment, and RVOL.
4. effective_conviction (float): 0.0 on dead days, otherwise raw_conviction.
5. rvol (float): Relative volume vs 20-period moving average.
6. range_atr_ratio (float): Current True Range relative to 14-period ATR.
"""

from __future__ import annotations
from collections import deque
import logging
import numpy as np
import pandas as pd


import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

log = logging.getLogger(__name__)

from core.symbol_state import symbol_state_registry

_HISTORY_LEN = 252
_MIN_HISTORY = 60  # Cold-start threshold before percentile logic activates


def _get_percentile_thresholds(symbol: str) -> dict | None:
    """Returns rolling 10th-percentile thresholds for this symbol, or None if under cold-start floor."""
    state = symbol_state_registry.get(symbol)
    with state._lock:
        if len(state.range_atr_history) < _MIN_HISTORY:
            return None
        range_arr = np.array(state.range_atr_history)
        rvol_arr = np.array(state.rvol_history)
        vol_arr = np.array(state.realized_vol_history)
        return {
            "range_atr_p10": float(np.percentile(range_arr, 10)),
            "rvol_p10": float(np.percentile(rvol_arr, 10)),
            "vol_p10": float(np.percentile(vol_arr, 10)),
        }


def _update_history(symbol: str, range_atr_ratio: float, rvol: float, realized_vol: float) -> None:
    state = symbol_state_registry.get(symbol)
    state.add_range_atr(range_atr_ratio)
    state.add_rvol(rvol)
    state.add_realized_vol(realized_vol)


def _seed_history_if_needed(df: pd.DataFrame, symbol: str) -> None:
    """Pre-seeds rolling history buffer from historical OHLCV bars if available."""
    state = symbol_state_registry.get(symbol)
    with state._lock:
        if len(state.range_atr_history) >= _MIN_HISTORY:
            return
    if df is None or len(df) < 20:
        return

    high_low = df["High"] - df["Low"]
    high_prev = (df["High"] - df["Close"].shift(1)).abs()
    low_prev = (df["Low"] - df["Close"].shift(1)).abs()
    tr = pd.concat([high_low, high_prev, low_prev], axis=1).max(axis=1)

    atr_14 = tr.rolling(14, min_periods=5).mean()
    vol_sma = df["Volume"].rolling(20, min_periods=5).mean()
    log_ret = np.log(df["Close"] / df["Close"].shift(1))
    real_vol = np.sqrt(log_ret.ewm(span=5, adjust=False).var() * 252)

    for idx in range(max(15, len(df) - 252), len(df) - 1):
        c_tr = tr.iloc[idx]
        c_atr = atr_14.iloc[idx]
        c_vol = df["Volume"].iloc[idx]
        c_vsma = vol_sma.iloc[idx]
        c_rv = real_vol.iloc[idx]

        r_atr = float(c_tr / max(1e-6, c_atr)) if pd.notna(c_atr) and c_atr > 0 else 1.0
        rv_ratio = float(c_vol / max(1.0, c_vsma)) if pd.notna(c_vsma) and c_vsma > 0 else 1.0
        r_vol = float(c_rv) if pd.notna(c_rv) else 0.01

        state.add_range_atr(r_atr)
        state.add_rvol(rv_ratio)
        state.add_realized_vol(r_vol)


def compute_dead_day_and_conviction(
    df: pd.DataFrame,
    ml_confidence: float,
    s_flow: float = 0.0,
    s_composite_dir: float = 0.0,
    is_crypto: bool = False,
    symbol: str = "DEFAULT"
) -> dict:
    """
    Computes dead-day filter flag and final unified conviction score.
    Uses rolling 252-bar 10th-percentile thresholding when ENABLE_PERCENTILE_DEAD_DAY is True,
    with a cold-start static fallback floor for < 60 historical observations.
    """
    if df is None or len(df) < 5:
        # Fallback for empty or minimal dataframe
        return {
            "is_dead_day": False,
            "dead_day_reason": "Insufficient history (<5 bars)",
            "raw_conviction": round(max(0.0, min(1.0, ml_confidence)), 4),
            "effective_conviction": round(max(0.0, min(1.0, ml_confidence)), 4),
            "rvol": 1.0,
            "range_atr_ratio": 1.0,
        }

    high_low = df["High"] - df["Low"]
    high_prev = (df["High"] - df["Close"].shift(1)).abs()
    low_prev = (df["Low"] - df["Close"].shift(1)).abs()
    tr = pd.concat([high_low, high_prev, low_prev], axis=1).max(axis=1)

    window = min(14, len(tr))
    atr_14 = tr.rolling(window).mean().iloc[-1]
    current_tr = tr.iloc[-1]
    range_atr_ratio = float(current_tr / max(1e-6, atr_14))

    vol_window = min(20, len(df))
    vol_sma = df["Volume"].rolling(vol_window).mean().iloc[-1]
    rvol = float(df["Volume"].iloc[-1] / max(1.0, vol_sma))

    log_ret = np.log(df["Close"] / df["Close"].shift(1))
    realized_vol = float(np.sqrt(log_ret.ewm(span=min(5, len(df)), adjust=False).var() * 252).iloc[-1])

    # Dead-Day Filter Rules — dynamic rolling percentile with cold-start static fallback
    use_percentiles = getattr(config, "ENABLE_PERCENTILE_DEAD_DAY", True)
    _seed_history_if_needed(df, symbol)
    _update_history(symbol, range_atr_ratio, rvol, realized_vol)

    pct = _get_percentile_thresholds(symbol) if use_percentiles else None

    if pct is not None:
        range_atr_thresh_a = pct["range_atr_p10"]
        range_atr_thresh_b = pct["range_atr_p10"] * 1.25
        range_atr_thresh_c = pct["range_atr_p10"] * 1.17
        rvol_thresh = pct["rvol_p10"]
        vol_thresh = pct["vol_p10"]
        state_n = len(symbol_state_registry.get(symbol).range_atr_history)
        filter_mode = f"Percentile P10 (N={state_n})"
    else:
        range_atr_thresh_a, range_atr_thresh_b, range_atr_thresh_c = 0.60, 0.75, 0.70
        rvol_thresh = 0.65
        vol_thresh = 0.025 if is_crypto else 0.009
        filter_mode = "Static Fallback"

    cond_a = range_atr_ratio < range_atr_thresh_a
    cond_b = (rvol < rvol_thresh) and (range_atr_ratio < range_atr_thresh_b)
    cond_c = (realized_vol < vol_thresh) and (range_atr_ratio < range_atr_thresh_c)
    is_dead_day = bool(cond_a or cond_b or cond_c)

    dead_reason = (
        f"[{filter_mode}] Range/ATR: {range_atr_ratio:.2f}, RVOL: {rvol:.2f}x, Vol: {realized_vol:.4f}"
        if is_dead_day
        else "Active Market Conditions"
    )

    # Composite Conviction Score
    direction_sign = 1.0 if s_composite_dir > 0 else (-1.0 if s_composite_dir < 0 else 0.0)
    flow_alignment = float(s_flow * direction_sign)  # [-1.0, +1.0]
    flow_multiplier = 1.0 + (flow_alignment / 2.0)  # [0.5, 1.5]
    rvol_multiplier = float(np.clip(rvol, 0.5, 1.2))

    conviction_raw = float(ml_confidence * flow_multiplier * rvol_multiplier)
    conviction_score = float(np.clip(conviction_raw, 0.0, 1.0))
    effective_conviction = 0.0 if is_dead_day else conviction_score

    return {
        "is_dead_day": is_dead_day,
        "dead_day_reason": dead_reason,
        "raw_conviction": round(conviction_score, 4),
        "effective_conviction": round(effective_conviction, 4),
        "rvol": round(rvol, 2),
        "range_atr_ratio": round(range_atr_ratio, 2),
        "filter_mode": filter_mode,
    }

