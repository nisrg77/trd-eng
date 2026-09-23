"""
alpha_overlay/vap_cvd.py — Predictive Microstructure Engine

Tracks Volume-at-Price (VAP) and Cumulative Volume Delta (CVD) per instrument.

Design constraints (from chng.md §2):
  • Only instruments in config.CRYPTO_INSTRUMENTS are fed — aggTrade provides
    maker/taker classification. Equities/futures return None/0.0 until a paid
    tick feed is added (Phase 6).
  • VAP is maintained as an incremental fixed-bin histogram (config.VAP_BIN_COUNT
    bins). Gaussian smoothing is applied ONLY when VPOC/VAH/VAL are queried,
    never per tick.
  • CVD divergence detection uses rolling local extrema over a configurable
    window (config.VAP_DIVERGENCE_WINDOW, default 100 ticks).

Public API
----------
ingest_trade(symbol, price, qty, is_aggressor_buy)
    Feed a single classified trade into the VAP histogram and CVD accumulator.

get_vpoc(symbol) -> float | None
    Price bin with the highest smoothed volume. None if no data.

get_vah_val(symbol, value_area_pct=None) -> tuple[float, float] | None
    (Value Area High, Value Area Low) enclosing `value_area_pct` of total
    volume around the VPOC. None if no data.

get_cvd(symbol) -> float
    Latest raw Cumulative Volume Delta.

get_predictive_signal(symbol) -> float
    S_predictive ∈ [-1, +1]. Positive = bullish absorption / divergence.
    0.0 if symbol not supported or insufficient data.

reset(symbol)
    Clear all state for the given symbol (useful for testing / day-roll).
"""

from __future__ import annotations

import threading
import logging
from collections import deque
from typing import Deque

import numpy as np

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Per-symbol state containers
# ─────────────────────────────────────────────────────────────────────────────

_lock = threading.Lock()

# VAP: fixed-bin histogram per symbol
#   _vap_bins[symbol]  = np.ndarray of shape (VAP_BIN_COUNT,)  — volume per bin
#   _vap_edges[symbol] = np.ndarray of shape (VAP_BIN_COUNT+1,) — bin edges
#   _vap_lo[symbol]    = float  (min price seen, expands dynamically)
#   _vap_hi[symbol]    = float  (max price seen, expands dynamically)
_vap_bins:  dict[str, np.ndarray] = {}
_vap_edges: dict[str, np.ndarray] = {}
_vap_lo:    dict[str, float] = {}
_vap_hi:    dict[str, float] = {}

# CVD: running net signed volume
_cvd: dict[str, float] = {}

# Rolling history for divergence detection
_price_hist: dict[str, Deque[float]] = {}
_cvd_hist:   dict[str, Deque[float]] = {}

# Track total trade count per symbol (guard against querying with < W ticks)
_trade_count: dict[str, int] = {}

_BIN_COUNT = getattr(config, "VAP_BIN_COUNT", 500)
_VALUE_AREA_PCT = getattr(config, "VAP_VALUE_AREA_PCT", 0.70)
_DIV_WINDOW = getattr(config, "VAP_DIVERGENCE_WINDOW", 100)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_supported(symbol: str) -> bool:
    """Only crypto instruments have an aggTrade feed."""
    return symbol in config.CRYPTO_INSTRUMENTS


def _rebuild_edges(lo: float, hi: float) -> np.ndarray:
    """Return bin edges for [lo, hi] with _BIN_COUNT bins."""
    return np.linspace(lo, hi, _BIN_COUNT + 1)


def _migrate_bins(symbol: str, new_lo: float, new_hi: float) -> None:
    """
    Expand the histogram range to include new_lo / new_hi.
    Existing volume is redistributed into the new bin layout proportionally.
    """
    old_edges = _vap_edges[symbol]
    old_bins  = _vap_bins[symbol]
    old_lo    = _vap_lo[symbol]
    old_hi    = _vap_hi[symbol]

    lo = min(old_lo, new_lo)
    hi = max(old_hi, new_hi)

    new_edges = _rebuild_edges(lo, hi)
    new_bins  = np.zeros(_BIN_COUNT, dtype=np.float64)

    # Map each old bin's midpoint into the new grid
    old_mids = (old_edges[:-1] + old_edges[1:]) / 2.0
    for i, (mid, vol) in enumerate(zip(old_mids, old_bins)):
        if vol == 0.0:
            continue
        idx = int(np.searchsorted(new_edges, mid, side="right")) - 1
        idx = max(0, min(_BIN_COUNT - 1, idx))
        new_bins[idx] += vol

    _vap_edges[symbol] = new_edges
    _vap_bins[symbol]  = new_bins
    _vap_lo[symbol]    = lo
    _vap_hi[symbol]    = hi


def _init_symbol(symbol: str, first_price: float) -> None:
    """Initialise all state for a symbol at its first observed price."""
    half_range = first_price * 0.10  # ±10% initial window
    lo = first_price - half_range
    hi = first_price + half_range

    _vap_lo[symbol]    = lo
    _vap_hi[symbol]    = hi
    _vap_edges[symbol] = _rebuild_edges(lo, hi)
    _vap_bins[symbol]  = np.zeros(_BIN_COUNT, dtype=np.float64)
    _cvd[symbol]       = 0.0
    _price_hist[symbol] = deque(maxlen=_DIV_WINDOW)
    _cvd_hist[symbol]   = deque(maxlen=_DIV_WINDOW)
    _trade_count[symbol] = 0


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def ingest_trade(
    symbol: str,
    price: float,
    qty: float,
    is_aggressor_buy: bool,
) -> None:
    """
    Feed a single classified aggTrade into the VAP histogram and CVD tracker.

    Parameters
    ----------
    symbol            : Instrument identifier (e.g. "BTC-USD")
    price             : Trade price
    qty               : Trade quantity (always positive)
    is_aggressor_buy  : True if the aggressor was a buyer (taker-side buy)
    """
    if not _is_supported(symbol):
        return

    with _lock:
        if symbol not in _vap_bins:
            _init_symbol(symbol, price)

        # Expand histogram range if price falls outside current window
        lo = _vap_lo[symbol]
        hi = _vap_hi[symbol]
        if price < lo or price > hi:
            pad = abs(price - ((lo + hi) / 2.0)) * 0.20
            new_lo = min(lo, price - pad)
            new_hi = max(hi, price + pad)
            _migrate_bins(symbol, new_lo, new_hi)

        # Bin index for this trade
        edges = _vap_edges[symbol]
        idx = int(np.searchsorted(edges, price, side="right")) - 1
        idx = max(0, min(_BIN_COUNT - 1, idx))
        _vap_bins[symbol][idx] += qty

        # CVD update
        signed_qty = qty if is_aggressor_buy else -qty
        _cvd[symbol] = _cvd.get(symbol, 0.0) + signed_qty

        # Rolling history for divergence detection
        _price_hist[symbol].append(price)
        _cvd_hist[symbol].append(_cvd[symbol])
        _trade_count[symbol] = _trade_count.get(symbol, 0) + 1


def get_vpoc(symbol: str) -> float | None:
    """
    Returns the price of the volume-point-of-control (VPOC) after applying
    Gaussian smoothing (σ=1) over the histogram.

    Returns None if symbol has no data or is not supported.
    """
    if not _is_supported(symbol):
        return None

    with _lock:
        if symbol not in _vap_bins or _vap_bins[symbol].sum() == 0:
            return None

        try:
            from scipy.ndimage import gaussian_filter1d
            smoothed = gaussian_filter1d(_vap_bins[symbol].astype(float), sigma=1)
        except ImportError:
            smoothed = _vap_bins[symbol]

        peak_idx  = int(np.argmax(smoothed))
        edges     = _vap_edges[symbol]
        vpoc_price = (edges[peak_idx] + edges[peak_idx + 1]) / 2.0
        return float(vpoc_price)


def get_vah_val(
    symbol: str,
    value_area_pct: float | None = None,
) -> tuple[float, float] | None:
    """
    Returns (Value Area High, Value Area Low) enclosing `value_area_pct` of
    total volume, walking outward from the VPOC bin.

    Returns None if symbol has no data or is not supported.
    """
    if not _is_supported(symbol):
        return None

    if value_area_pct is None:
        value_area_pct = _VALUE_AREA_PCT

    with _lock:
        if symbol not in _vap_bins or _vap_bins[symbol].sum() == 0:
            return None

        try:
            from scipy.ndimage import gaussian_filter1d
            smoothed = gaussian_filter1d(_vap_bins[symbol].astype(float), sigma=1)
        except ImportError:
            smoothed = _vap_bins[symbol].astype(float)

        total_vol   = smoothed.sum()
        target_vol  = total_vol * value_area_pct
        peak_idx    = int(np.argmax(smoothed))

        low_idx  = peak_idx
        high_idx = peak_idx
        acc_vol  = smoothed[peak_idx]

        while acc_vol < target_vol:
            can_go_lower  = low_idx  > 0
            can_go_higher = high_idx < _BIN_COUNT - 1

            if not can_go_lower and not can_go_higher:
                break

            add_low  = smoothed[low_idx  - 1] if can_go_lower  else -1.0
            add_high = smoothed[high_idx + 1] if can_go_higher else -1.0

            if add_high >= add_low:
                high_idx += 1
                acc_vol  += add_high
            else:
                low_idx  -= 1
                acc_vol  += add_low

        edges = _vap_edges[symbol]
        vah = (edges[high_idx] + edges[high_idx + 1]) / 2.0
        val = (edges[low_idx]  + edges[low_idx  + 1]) / 2.0
        return float(vah), float(val)


def get_cvd(symbol: str) -> float:
    """Returns the latest raw Cumulative Volume Delta. 0.0 if no data."""
    if not _is_supported(symbol):
        return 0.0
    with _lock:
        return _cvd.get(symbol, 0.0)


def get_predictive_signal(symbol: str) -> float:
    """
    S_predictive ∈ [-1, +1].

    Detects bullish or bearish absorption divergence:
      - Bullish: price making lower lows while CVD making higher lows
        (demand absorption — buyers absorbing sells silently).
      - Bearish: price making higher highs while CVD making lower highs
        (supply absorption — sellers absorbing buys silently).

    Uses local min/max over the rolling divergence window to avoid
    sensitivity to single-tick noise.

    Returns 0.0 if symbol is not supported or has < half a window of data.
    """
    if not _is_supported(symbol):
        return 0.0

    with _lock:
        count = _trade_count.get(symbol, 0)
        if count < max(10, _DIV_WINDOW // 2):
            return 0.0

        prices = list(_price_hist[symbol])
        cvds   = list(_cvd_hist[symbol])

    n = len(prices)
    if n < 4:
        return 0.0

    half = n // 2
    # Split rolling window into first and second halves for trend comparison
    p_early = np.array(prices[:half])
    p_late  = np.array(prices[half:])
    c_early = np.array(cvds[:half])
    c_late  = np.array(cvds[half:])

    p_high_early, p_high_late = p_early.max(), p_late.max()
    p_low_early,  p_low_late  = p_early.min(), p_late.min()
    c_high_early, c_high_late = c_early.max(), c_late.max()
    c_low_early,  c_low_late  = c_early.min(), c_late.min()

    score = 0.0

    # Bullish divergence: price LL but CVD HL
    if p_low_late < p_low_early and c_low_late > c_low_early:
        # Strength proportional to the gap magnitude
        price_drop = (p_low_early - p_low_late) / max(abs(p_low_early), 1e-9)
        cvd_rise   = (c_low_late  - c_low_early) / (abs(c_low_early) + 1.0)
        score += min(1.0, (price_drop + cvd_rise) * 2.0)

    # Bearish divergence: price HH but CVD LH
    if p_high_late > p_high_early and c_high_late < c_high_early:
        price_rise  = (p_high_late  - p_high_early) / max(abs(p_high_early), 1e-9)
        cvd_fall    = (c_high_early - c_high_late)   / (abs(c_high_early) + 1.0)
        score -= min(1.0, (price_rise + cvd_fall) * 2.0)

    return float(np.clip(score, -1.0, 1.0))


def reset(symbol: str) -> None:
    """Clear all VAP/CVD state for `symbol`. Useful for session roll or testing."""
    with _lock:
        for store in (_vap_bins, _vap_edges, _vap_lo, _vap_hi,
                      _cvd, _price_hist, _cvd_hist, _trade_count):
            store.pop(symbol, None)
    log.info("vap_cvd: reset state for %s", symbol)
