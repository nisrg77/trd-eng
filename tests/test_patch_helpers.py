"""Pure unit tests — no repo dependencies. Run:  pytest tests/test_patch_helpers.py"""
import types

import numpy as np
import pandas as pd
import pytest

from core import patch_helpers as h


def _prices(n=365, sigma=0.02, seed=0, start=100.0):
    rng = np.random.default_rng(seed)
    return pd.Series(start * np.exp(np.cumsum(rng.normal(0, sigma, n))))


# ── garch_vol units / annualized→daily ───────────────────────────────────────
def test_annualized_daily_roundtrip():
    assert h.annualized_to_daily_vol(h.daily_to_annualized_vol(0.02)) == pytest.approx(0.02)
    assert h.annualized_to_daily_vol(0.6) == pytest.approx(0.6 / np.sqrt(252))


def test_pipeline_formula_is_annualized_and_daily_matches_after_conversion():
    close = _prices()
    log_ret = np.log(close / close.shift(1))
    old_annualized = np.sqrt(log_ret.ewm(span=20, adjust=False).var() * 252)  # pipeline.compute_garch_vol
    daily = h.compute_daily_vol(close, span=20)
    np.testing.assert_allclose(old_annualized.dropna(), daily.dropna() * np.sqrt(252), rtol=1e-9)
    # annualized values live far above the 0.008/0.020 regime thresholds ...
    assert old_annualized.dropna().median() > 0.020
    # ... while daily values live in the range those thresholds were written for.
    assert 0.005 < daily.dropna().median() < 0.05


def test_static_thresholds_against_annualized_vol_are_always_high_vol():
    """Documents the live bug: annualized vol never falls under REGIME_VOL_THRESHOLD_HIGH."""
    close = _prices()
    ann = np.sqrt(np.log(close / close.shift(1)).ewm(span=5, adjust=False).var() * 252).dropna()
    assert (ann > 0.020).mean() > 0.95


def test_regime_thresholds_fallback_and_percentiles():
    assert h.regime_thresholds([0.01] * 10) == (0.008, 0.020)
    hist = np.linspace(0.01, 0.05, 300)
    lo, hi = h.regime_thresholds(hist)
    assert 0.01 < lo < hi < 0.05
    assert np.mean(hist[-252:] < lo) == pytest.approx(0.33, abs=0.03)


# ── ATR ──────────────────────────────────────────────────────────────────────
def test_true_atr_known_values():
    df = pd.DataFrame(
        {"High": [10, 12, 13], "Low": [8, 9, 11], "Close": [9, 11, 12]}, dtype=float
    )
    atr = h.true_atr(df, period=2)
    # TR = [2, max(3, 3, 0)=3, max(2, 2, 0)=2]  -> rolling(2) mean
    assert atr.iloc[1] == pytest.approx(2.5)
    assert atr.iloc[2] == pytest.approx(2.5)


def test_resolve_atr_prefers_ohlc_then_converts_annualized():
    assert h.resolve_atr({"atr_14": 850.0, "garch_vol": 0.6}, 60000) == 850.0
    atr = h.resolve_atr({"garch_vol": 0.6}, 60000)
    assert atr == pytest.approx(60000 * 0.6 / np.sqrt(252))
    assert atr < 0.10 * 60000          # NOT price * annualized vol (= 36,000)
    assert h.resolve_atr({}, 100.0) == pytest.approx(1.5)


# ── IFF: threshold + scaling consistency ─────────────────────────────────────
def test_iff_params_single_source_of_truth():
    assert h.iff_params(types.SimpleNamespace()) == (0.5, 0.5)
    assert h.iff_params(types.SimpleNamespace(IFF_VETO_THRESHOLD=0.65, IFF_SOFT_SCALE=0.3)) == (0.65, 0.3)


@pytest.mark.parametrize("sig,flow,veto", [
    (0.5, -0.51, True), (0.5, -0.50, False), (-0.5, 0.51, True), (-0.5, 0.50, False),
    (0.5, 0.9, False), (-0.5, -0.9, False),
])
def test_iff_veto_boundary(sig, flow, veto):
    assert h.iff_is_veto(sig, flow, 0.5) is veto


def test_iff_scaling_is_direction_aware():
    long_aligned = h.iff_soft_scale(0.5, +0.4, 0.5)
    long_opposed = h.iff_soft_scale(0.5, -0.4, 0.5)
    short_aligned = h.iff_soft_scale(-0.5, -0.4, 0.5)
    short_opposed = h.iff_soft_scale(-0.5, +0.4, 0.5)
    assert long_aligned > 0.5 > long_opposed
    assert abs(short_aligned) > 0.5 > abs(short_opposed)      # the old code reversed this
    assert short_aligned == pytest.approx(-long_aligned)      # mirror symmetry


def test_iff_gate_bounds_and_symmetry():
    for s in np.linspace(-1, 1, 21):
        for f in np.linspace(-1, 1, 21):
            g, v = h.iff_gate(s, f)
            assert -1.0 <= g <= 1.0
            g2, v2 = h.iff_gate(-s, -f)
            assert g2 == pytest.approx(-g) and v2 == v
    assert h.iff_gate(0.4, -0.9) == (0.0, True)


def test_flow_alignment_mult():
    assert h.flow_alignment_mult(+0.4, +0.3) > 1 > h.flow_alignment_mult(+0.4, -0.3)
    assert h.flow_alignment_mult(-0.4, -0.3) > 1 > h.flow_alignment_mult(-0.4, +0.3)


# ── labels: final bar excluded ───────────────────────────────────────────────
def test_next_bar_labels_last_bar_invalid_and_alignment():
    close = np.array([100, 101, 100, 102, 102, 103], dtype=float)
    y, valid = h.next_bar_labels(close)
    assert valid.tolist() == [True, True, True, True, True, False]
    assert y[:5].tolist() == [1, -1, 1, 0, 1]     # y[t] = sign(close[t+1]/close[t])
    assert y[-1] == 0.0 and not valid[-1]         # the artificial zero must never be trained on


def test_sequence_samples_exclude_final_artificial_label():
    n, f, L = 40, 4, 10
    X = np.arange(n * f, dtype=np.float32).reshape(n, f)
    close = 100 + np.cumsum(np.random.default_rng(1).normal(0, 1, n))
    y, valid = h.next_bar_labels(close)
    Xs, ys = h.build_sequence_samples(X, y, valid, L)
    assert Xs.shape == (n - L, L, f)              # (n-L+1) windows minus the unlabeled last one
    # last kept window ends at bar n-2 and pairs with y[n-2]
    np.testing.assert_array_equal(Xs[-1], X[n - 2 - L + 1: n - 1])
    assert ys[-1] == y[n - 2]
    assert len(ys) == valid[L - 1:].sum()
    with pytest.raises(ValueError):
        h.build_sequence_samples(X[:5], y[:5], valid[:5], L)


# ── fractional differentiation ───────────────────────────────────────────────
@pytest.mark.parametrize("n", [250, 365])
def test_frac_diff_ffd_has_many_valid_values(n):
    fd = h.frac_diff_ffd(_prices(n), d=0.4)
    assert fd.notna().sum() > 0.5 * n            # old implementation: exactly 1


def test_frac_diff_ffd_is_causal():
    s = _prices(300)
    base = h.frac_diff_ffd(s)
    s2 = s.copy()
    s2.iloc[-1] *= 3.0                            # perturb only the newest bar
    pert = h.frac_diff_ffd(s2)
    np.testing.assert_array_equal(base.iloc[:-1].to_numpy(), pert.iloc[:-1].to_numpy())


# ── simulated-OMS stop maths ─────────────────────────────────────────────────
def test_initial_stop_uses_atr_and_never_goes_negative():
    assert h.initial_stop(100.0, 2.0, True) == pytest.approx(96.0)
    assert h.initial_stop(100.0, 2.0, False) == pytest.approx(104.0)
    assert h.initial_stop(100.0, None, True) == pytest.approx(98.0)          # 2 % fallback
    # the old annualized-vol "ATR" (60 % of price) is clamped instead of producing a negative stop
    assert h.initial_stop(60000.0, 36000.0, True) == pytest.approx(45000.0)


def test_ratchet_only_tightens():
    s = h.initial_stop(100.0, 2.0, True)                      # 96
    s = h.ratchet_stop(s, 110.0, 2.0, True)                   # 106
    assert s == pytest.approx(106.0)
    assert h.ratchet_stop(s, 104.0, 2.0, True) == pytest.approx(106.0)   # price fell: stop holds
    ss = h.initial_stop(100.0, 2.0, False)                    # 104
    ss = h.ratchet_stop(ss, 90.0, 2.0, False)                 # 94
    assert ss == pytest.approx(94.0)
    assert h.ratchet_stop(ss, 96.0, 2.0, False) == pytest.approx(94.0)
