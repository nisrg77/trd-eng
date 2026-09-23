"""
tests/test_iff.py — Unit tests for alpha_overlay.iff

Tests verify:
  • IFF veto is applied when ML signal and flow score conflict strongly.
  • IFF soft-scale is applied when flow is aligned or neutral.
  • S_flow sizing cap is always respected in the execution engine path.
  • get_flow_score() always returns a value in [-1, +1].
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import numpy as np

import config
from alpha_overlay import vap_cvd
from alpha_overlay.iff import get_flow_score
from brain.meta_aggregator import MetaAggregator


SYM_CRYPTO  = "BTC-USD"
SYM_EQUITY  = "AAPL"


@pytest.fixture(autouse=True)
def reset_crypto():
    vap_cvd.reset(SYM_CRYPTO)
    yield
    vap_cvd.reset(SYM_CRYPTO)


# ─────────────────────────────────────────────────────────────────────────────
# get_flow_score — range and safety
# ─────────────────────────────────────────────────────────────────────────────

def test_flow_score_in_range_crypto():
    """S_flow must always be in [-1, +1] for crypto."""
    for obi in [-1.0, -0.5, 0.0, 0.5, 1.0]:
        s = get_flow_score(SYM_CRYPTO, obi)
        assert -1.0 <= s <= 1.0, f"flow_score={s} out of range for obi={obi}"


def test_flow_score_in_range_equity():
    """S_flow must always be in [-1, +1] for equities."""
    for obi in [-1.0, 0.0, 1.0]:
        s = get_flow_score(SYM_EQUITY, obi)
        assert -1.0 <= s <= 1.0


def test_flow_score_pure_obi_crypto():
    """
    With no VAP data (CVD=0, COT=0), S_flow should be driven only by OBI.
    For crypto weights [0.20, 0.50, 0.30]: S_flow = 0.0 + 0.0 + 0.30 * obi
    """
    s = get_flow_score(SYM_CRYPTO, obi_rho=1.0)
    # w_obi for crypto = 0.30; COT and CVD are 0
    expected = 0.30 * 1.0
    assert abs(s - expected) < 0.01, f"Expected ≈{expected}, got {s}"


def test_flow_score_pure_obi_equity():
    """
    For equity weights [0.50, 0.30, 0.20]: S_flow = 0.0 + 0.0 + 0.20 * obi
    """
    s = get_flow_score(SYM_EQUITY, obi_rho=1.0)
    expected = 0.20 * 1.0
    assert abs(s - expected) < 0.01, f"Expected ≈{expected}, got {s}"


def test_flow_score_obi_clipped():
    """OBI outside [-1,+1] should be clipped; result still in range."""
    s = get_flow_score(SYM_CRYPTO, obi_rho=99.0)
    assert -1.0 <= s <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# MetaAggregator & IFF Gate — Separation of Concerns & Graduated Threshold
# ─────────────────────────────────────────────────────────────────────────────

def _make_ma():
    return MetaAggregator()


def test_meta_aggregator_leaves_s_composite_untouched():
    """MetaAggregator should only blend models by regime weights; untouched by IFF."""
    ma = _make_ma()
    result = ma.aggregate(
        ridge_signal=0.6,
        xgb_signal=0.6,
        lstm_signal=0.6,
        garch_vol=0.010,
    )
    # Untouched blended signal
    assert abs(result["blended_signal"] - 0.6) < 1e-4


def test_apply_iff_gate_soft_scale_when_not_violating_threshold():
    """
    With crypto weights [0.20, 0.50, 0.30] and obi=-1.0 → S_flow = -0.30.
    Since |-0.30| <= 0.50 threshold, NO hard veto occurs; soft scale is applied:
        S_composite * (1 + 0.5 * S_flow) = 0.8 * (1 + 0.5 * (-0.30)) = 0.8 * 0.85 = 0.68.
    """
    from alpha_overlay.iff import apply_iff_gate

    s_composite = 0.8
    gated_signal, flow_score, iff_veto = apply_iff_gate(
        s_composite=s_composite,
        symbol=SYM_CRYPTO,
        obi_rho=-1.0,
    )
    assert iff_veto is False
    assert abs(flow_score - (-0.30)) < 0.01
    assert abs(gated_signal - 0.68) < 0.02


def test_apply_iff_gate_hard_veto_when_opposing_and_exceeding_threshold():
    """
    Hard veto only when ML direction opposes flow and |S_flow| > 0.5.
    When threshold is 0.0 (or simulated high opposing flow), hard veto sets signal=0.0.
    """
    from alpha_overlay.iff import apply_iff_gate

    original_threshold = config.IFF_VETO_THRESHOLD
    config.IFF_VETO_THRESHOLD = 0.25  # Lower threshold so -0.30 triggers hard veto
    try:
        gated_signal, flow_score, iff_veto = apply_iff_gate(
            s_composite=0.8,
            symbol=SYM_CRYPTO,
            obi_rho=-1.0,  # S_flow ≈ -0.30 opposing LONG
        )
        assert iff_veto is True
        assert gated_signal == 0.0
    finally:
        config.IFF_VETO_THRESHOLD = original_threshold


def test_apply_iff_gate_aligned_flow_amplifies():
    """Aligned flow (LONG with S_flow > 0) amplifies S_composite: S * (1 + 0.5*S_flow)."""
    from alpha_overlay.iff import apply_iff_gate

    s_composite = 0.5
    gated_signal, flow_score, iff_veto = apply_iff_gate(
        s_composite=s_composite,
        symbol=SYM_CRYPTO,
        obi_rho=1.0,  # S_flow ≈ +0.30
    )
    assert iff_veto is False
    assert flow_score > 0
    # Expected: 0.5 * (1 + 0.5 * 0.30) = 0.5 * 1.15 = 0.575
    assert gated_signal > s_composite



# ─────────────────────────────────────────────────────────────────────────────
# Sizing cap — IFF multiplier never exceeds MAX_POSITION_SIZE_PCT
# ─────────────────────────────────────────────────────────────────────────────

def test_iff_sizing_cap():
    """
    Even with S_flow=+1.0 (max flow_mult=2.0), allocation_pct must not
    exceed MAX_POSITION_SIZE_PCT for the active risk profile.
    """
    from execution.engine import ExecutionEngine

    engine = ExecutionEngine()
    profile = config.RISK_PROFILES.get(config.ACTIVE_RISK_PROFILE, config.RISK_PROFILES["Balanced"])
    max_size = profile["MAX_POSITION_SIZE_PCT"]

    signal = {
        "instrument":        SYM_CRYPTO,
        "confidence_score":  1.0,     # max confidence → max Kelly allocation
        "direction_magnitude": 1.0,
        "obi_rho":           1.0,     # max bullish OBI → S_flow > 0
    }

    order = engine.size_order(signal, instrument_data={})
    if order is not None:
        assert order["portfolio_allocation_pct"] <= max_size + 1e-9, (
            f"Allocation {order['portfolio_allocation_pct']:.4f} exceeded "
            f"MAX_POSITION_SIZE_PCT {max_size:.4f}"
        )
