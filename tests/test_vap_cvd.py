"""
tests/test_vap_cvd.py — Unit tests for alpha_overlay.vap_cvd

Tests are self-contained and do not require a live Binance connection.
"""
import sys
import os

# Ensure project root is on path for both pytest and direct execution
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import numpy as np
from alpha_overlay import vap_cvd


# Use a crypto instrument so _is_supported() passes
SYM = "BTC-USD"


@pytest.fixture(autouse=True)
def reset_state():
    """Reset vap_cvd state before every test for isolation."""
    vap_cvd.reset(SYM)
    yield
    vap_cvd.reset(SYM)


# ─────────────────────────────────────────────────────────────────────────────
# VPOC
# ─────────────────────────────────────────────────────────────────────────────

def test_vpoc_returns_none_when_no_data():
    assert vap_cvd.get_vpoc(SYM) is None


def test_vpoc_single_price_bin():
    """All volume at one price → VPOC ≈ that price (within one bin width)."""
    for _ in range(20):
        vap_cvd.ingest_trade(SYM, 30_000.0, 1.0, True)

    vpoc = vap_cvd.get_vpoc(SYM)
    assert vpoc is not None
    # VPOC should be within 1% of the fill price
    assert abs(vpoc - 30_000.0) < 300.0, f"VPOC={vpoc} too far from 30000"


def test_vpoc_highest_volume_bin():
    """When two price clusters exist, VPOC should point to the denser one."""
    # Light volume at 29000, heavy volume at 31000
    for _ in range(5):
        vap_cvd.ingest_trade(SYM, 29_000.0, 1.0, True)
    for _ in range(50):
        vap_cvd.ingest_trade(SYM, 31_000.0, 1.0, True)

    vpoc = vap_cvd.get_vpoc(SYM)
    assert vpoc is not None
    assert vpoc > 30_000.0, f"VPOC={vpoc} should be nearer to 31000"


# ─────────────────────────────────────────────────────────────────────────────
# VAH / VAL
# ─────────────────────────────────────────────────────────────────────────────

def test_vah_val_returns_none_when_no_data():
    assert vap_cvd.get_vah_val(SYM) is None


def test_vah_val_straddle_70pct():
    """VAH/VAL should enclose ≥ 70% of total volume around the VPOC."""
    # Uniform volume across a range: 29000, 30000, 31000
    prices = [29_000.0, 30_000.0, 31_000.0]
    for p in prices:
        for _ in range(30):
            vap_cvd.ingest_trade(SYM, p, 1.0, True)

    levels = vap_cvd.get_vah_val(SYM)
    assert levels is not None, "Expected VAH/VAL to be computed"
    vah, val = levels
    assert vah > val, "VAH must be above VAL"
    # With only 3 price levels and 70% requirement the range must cover at least 2
    assert vah >= 30_000.0
    assert val <= 30_000.0


def test_vah_above_val():
    """Sanity: VAH is always > VAL."""
    for _ in range(10):
        vap_cvd.ingest_trade(SYM, 40_000.0, 1.0, False)
    levels = vap_cvd.get_vah_val(SYM)
    if levels:
        assert levels[0] > levels[1]


# ─────────────────────────────────────────────────────────────────────────────
# CVD
# ─────────────────────────────────────────────────────────────────────────────

def test_cvd_starts_at_zero():
    assert vap_cvd.get_cvd(SYM) == 0.0


def test_cvd_buy_accumulation():
    """All aggressor buys → CVD should be positive."""
    for _ in range(10):
        vap_cvd.ingest_trade(SYM, 30_000.0, 2.0, True)
    assert vap_cvd.get_cvd(SYM) == pytest.approx(20.0)


def test_cvd_sell_accumulation():
    """All aggressor sells → CVD should be negative."""
    for _ in range(5):
        vap_cvd.ingest_trade(SYM, 30_000.0, 3.0, False)
    assert vap_cvd.get_cvd(SYM) == pytest.approx(-15.0)


def test_cvd_mixed_trades():
    """10 buy qty=1 and 4 sell qty=1 → net CVD = +6."""
    for _ in range(10):
        vap_cvd.ingest_trade(SYM, 30_000.0, 1.0, True)
    for _ in range(4):
        vap_cvd.ingest_trade(SYM, 30_000.0, 1.0, False)
    assert vap_cvd.get_cvd(SYM) == pytest.approx(6.0)


# ─────────────────────────────────────────────────────────────────────────────
# Predictive signal range
# ─────────────────────────────────────────────────────────────────────────────

def test_predictive_signal_returns_zero_insufficient_data():
    """With fewer ticks than the window guard, should return 0.0."""
    for _ in range(3):
        vap_cvd.ingest_trade(SYM, 30_000.0, 1.0, True)
    assert vap_cvd.get_predictive_signal(SYM) == 0.0


def test_predictive_signal_in_range():
    """After filling enough ticks, signal must be ∈ [-1, +1]."""
    for i in range(200):
        p = 30_000.0 + (i % 50) * 10
        vap_cvd.ingest_trade(SYM, p, 1.0, True)
    s = vap_cvd.get_predictive_signal(SYM)
    assert -1.0 <= s <= 1.0


def test_non_crypto_symbol_returns_defaults():
    """Non-crypto symbol should not be tracked — all getters return safe defaults."""
    vap_cvd.ingest_trade("AAPL", 200.0, 100.0, True)  # should be silently ignored
    assert vap_cvd.get_vpoc("AAPL") is None
    assert vap_cvd.get_vah_val("AAPL") is None
    assert vap_cvd.get_cvd("AAPL") == 0.0
    assert vap_cvd.get_predictive_signal("AAPL") == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Price range expansion
# ─────────────────────────────────────────────────────────────────────────────

def test_histogram_expands_for_out_of_range_price():
    """Ingesting a price far outside the initial window should not raise."""
    vap_cvd.ingest_trade(SYM, 30_000.0, 1.0, True)
    vap_cvd.ingest_trade(SYM, 60_000.0, 1.0, True)  # 2× initial price
    vpoc = vap_cvd.get_vpoc(SYM)
    assert vpoc is not None


def test_reset_clears_state():
    """After reset, all getters return initial/empty values."""
    for _ in range(20):
        vap_cvd.ingest_trade(SYM, 30_000.0, 1.0, True)
    vap_cvd.reset(SYM)
    assert vap_cvd.get_vpoc(SYM) is None
    assert vap_cvd.get_cvd(SYM) == 0.0
