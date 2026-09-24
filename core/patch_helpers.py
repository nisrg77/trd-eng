"""
core/patch_helpers.py — shared, pure helpers for the trd-eng patch set.

Everything here is side-effect free (numpy / pandas only) so it can be unit-tested
without the rest of the repo. Existing modules call these instead of re-implementing
the logic in several places.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


# ── 1. Volatility units ──────────────────────────────────────────────────────
def annualized_to_daily_vol(ann_vol: float) -> float:
    return float(ann_vol) / float(np.sqrt(TRADING_DAYS))


def daily_to_annualized_vol(daily_vol: float) -> float:
    return float(daily_vol) * float(np.sqrt(TRADING_DAYS))


def compute_daily_vol(close: pd.Series, span: int = 20) -> pd.Series:
    """EWMA std of daily log returns (NOT annualized)."""
    log_ret = np.log(close / close.shift(1))
    return np.sqrt(log_ret.ewm(span=span, adjust=False).var())


def regime_thresholds(
    daily_vol_history,
    low_pct: float = 33.0,
    high_pct: float = 67.0,
    min_obs: int = 60,
    fallback: tuple[float, float] = (0.008, 0.020),
) -> tuple[float, float]:
    """
    Per-symbol regime cut-offs from the symbol's own trailing daily-vol history
    (causal: uses only values already observed). Falls back to static thresholds
    while there is too little history.
    """
    v = pd.Series(daily_vol_history, dtype=float)
    v = v.replace([np.inf, -np.inf], np.nan).dropna()
    v = v[v > 0]
    if len(v) < min_obs:
        return fallback
    lo, hi = np.percentile(v.iloc[-TRADING_DAYS:], [low_pct, high_pct])
    if not hi > lo:
        return fallback
    return float(lo), float(hi)


# ── 2. ATR ───────────────────────────────────────────────────────────────────
def true_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Rolling-mean true-range ATR from OHLC (columns High / Low / Close)."""
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def resolve_atr(features: dict, close_price: float, default_pct: float = 0.015) -> float:
    """
    Price-unit ATR for stops/targets. Prefers a real OHLC ATR; otherwise converts the
    ANNUALIZED garch_vol to a one-day move. Never returns annualized-vol * price.
    """
    atr = features.get("atr_14")
    if atr is not None and atr > 0:
        return float(atr)
    g = features.get("garch_vol")
    if g is not None and g > 0:
        return float(close_price) * annualized_to_daily_vol(g)
    return float(close_price) * default_pct


# ── 3. IFF gate (one implementation, sign-aware) ─────────────────────────────
def iff_params(cfg) -> tuple[float, float]:
    """(veto_threshold, soft_scale_coeff) — single source of truth."""
    return (
        float(getattr(cfg, "IFF_VETO_THRESHOLD", 0.5)),
        float(getattr(cfg, "IFF_SOFT_SCALE", 0.5)),
    )


def iff_is_veto(signal: float, flow: float, threshold: float) -> bool:
    return (signal > 0 and flow < -threshold) or (signal < 0 and flow > threshold)


def iff_soft_scale(signal: float, flow: float, coeff: float = 0.5) -> float:
    """
    Flow that AGREES with the signal strengthens it; flow that OPPOSES weakens it.
    (The old  s * (1 + c*flow)  did the reverse for short signals.)
    """
    sign = float(np.sign(signal))
    return float(np.clip(signal * (1.0 + coeff * flow * sign), -1.0, 1.0))


def iff_gate(
    signal: float, flow: float, threshold: float = 0.5, coeff: float = 0.5
) -> tuple[float, bool]:
    if iff_is_veto(signal, flow, threshold):
        return 0.0, True
    return iff_soft_scale(signal, flow, coeff), False


def flow_alignment_mult(direction: float, flow: float, lo: float = 0.5, hi: float = 1.5) -> float:
    """Allocation multiplier: >1 when flow agrees with direction, <1 when it opposes."""
    return float(np.clip(1.0 + flow * float(np.sign(direction)), lo, hi))


# ── 4. Labels (next-bar sign, final bar excluded) ────────────────────────────
def next_bar_labels(close) -> tuple[np.ndarray, np.ndarray]:
    """
    y[t] = sign(log(close[t+1] / close[t])).  The last bar has no future close, so
    valid[-1] is False; callers MUST train on y[valid], never on the filled 0.
    """
    c = pd.Series(close, dtype=float).reset_index(drop=True)
    r = np.log(c / c.shift(1)).shift(-1)
    valid = r.notna().to_numpy()
    y = np.sign(r.fillna(0.0)).to_numpy(dtype=np.float32)
    return y, valid


def build_sequence_samples(
    X: np.ndarray, y: np.ndarray, valid: np.ndarray, seq_len: int
) -> tuple[np.ndarray, np.ndarray]:
    """
    Window X[i-seq_len+1 : i+1] (ends at bar i, inclusive) is paired with y[i],
    exactly like the row-wise models pair X[i] with y[i]. Bars without a label
    are dropped.
    """
    n = len(X)
    if n < seq_len:
        raise ValueError(f"Not enough bars ({n}) to form sequences of length {seq_len}")
    idx = [i for i in range(seq_len - 1, n) if valid[i]]
    if not idx:
        return np.empty((0, seq_len, X.shape[1]), np.float32), np.empty((0,), np.float32)
    Xs = np.stack([X[i - seq_len + 1: i + 1] for i in idx]).astype(np.float32)
    return Xs, y[idx].astype(np.float32)


# ── 5. Fractional differentiation (fixed-width window) ───────────────────────
def ffd_weights(d: float, threshold: float = 1e-3, max_width: int = 100) -> np.ndarray:
    w = [1.0]
    for k in range(1, max_width):
        w_k = -w[-1] * (d - k + 1) / k
        if abs(w_k) < threshold:
            break
        w.append(w_k)
    return np.array(w[::-1])


def frac_diff_ffd(
    series: pd.Series, d: float = 0.4, threshold: float = 1e-3, max_width: int = 100
) -> pd.Series:
    """
    Fixed-width-window fractional differencing. The window is capped so a 250-365
    bar history yields ~150-265 valid values (the old code used width == len(series)
    and produced exactly ONE valid value).
    """
    w = ffd_weights(d, threshold, min(max_width, max(2, len(series) // 2)))
    width = len(w)
    x = series.to_numpy(dtype=float)
    out = np.full(len(x), np.nan)
    for i in range(width - 1, len(x)):
        win = x[i - width + 1: i + 1]
        if not np.isnan(win).any():
            out[i] = float(np.dot(w, win))
    return pd.Series(out, index=series.index)


# ── 6. Stops ─────────────────────────────────────────────────────────────────
def initial_stop(
    fill: float, atr: float | None, is_long: bool, k: float = 2.0,
    fallback_pct: float = 0.02, max_pct: float = 0.25,
) -> float:
    dist = k * atr if (atr and atr > 0) else fallback_pct * fill
    dist = min(dist, max_pct * fill)
    return fill - dist if is_long else fill + dist


def ratchet_stop(
    prev_stop: float, current: float, atr: float, is_long: bool,
    k: float = 2.0, max_pct: float = 0.25,
) -> float:
    dist = min(k * atr, max_pct * current)
    return max(prev_stop, current - dist) if is_long else min(prev_stop, current + dist)
