"""
Integration tests — run from the trd-eng repo root AFTER applying PATCH_GUIDE.md:

    cp -r trd_eng_patches/core/patch_helpers.py core/
    cp trd_eng_patches/tests/*.py tests/
    pytest tests/test_patch_helpers.py tests/test_repo_integration.py -q

Written against the patched API described in the guide. Tests skip if the repo
modules are not importable. If you named something differently, adjust the import.
"""
import inspect
import json
import os
import sys
from unittest import mock

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.environ.get("TRD_ENG_REPO", os.getcwd()))
config = pytest.importorskip("config")

SQRT252 = np.sqrt(252)


def _ohlcv(n=365, sigma=0.02, seed=1, start=60000.0):
    rng = np.random.default_rng(seed)
    close = start * np.exp(np.cumsum(rng.normal(0, sigma, n)))
    high, low = close * 1.01, close * 0.99
    idx = pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {"Open": close, "High": high, "Low": low, "Close": close, "Volume": 1000.0}, index=idx
    )


# ── 1 & 2. garch_vol units, annualized→daily, feature health ─────────────────
def test_pipeline_vol_units_and_features():
    P = pytest.importorskip("data_pipeline.pipeline")
    df = _ohlcv()
    ann = P.compute_garch_vol(df["Close"], 20)
    daily = P.compute_daily_vol(df["Close"], 20)
    np.testing.assert_allclose((ann / SQRT252).dropna(), daily.dropna(), rtol=1e-9)

    payload = P._build_payload(df, "BTC-USD")
    f = payload["features"]
    assert f["garch_vol_daily"] == pytest.approx(f["garch_vol"] / SQRT252, abs=2e-6)
    assert 0 < f["atr_14"] < 0.2 * df["Close"].iloc[-1]          # a price-unit ATR, not 60 % of price
    fd_hist = pd.Series(payload["_feature_history"]["frac_diff"])
    assert fd_hist.notna().sum() > 100                            # was exactly 1


def test_meta_aggregator_regime_uses_daily_units():
    from brain.meta_aggregator import MetaAggregator
    ma = MetaAggregator()
    thr = (0.008, 0.020)
    kw = dict(vol_thresholds=thr, vol_is_annualized=True)
    assert ma.aggregate(0.1, 0.1, 0.1, garch_vol=0.10, **kw)["regime_flag"] == "low_volatility"
    assert ma.aggregate(0.1, 0.1, 0.1, garch_vol=0.60, **kw)["regime_flag"] == "high_volatility"
    mid = ma.aggregate(0.1, 0.1, 0.1, garch_vol=0.20, **kw)["regime_flag"]
    assert mid in ("trending", "trending_up")                     # previously always high_volatility


# ── 3 & 4. IFF threshold + scaling consistency ───────────────────────────────
def test_iff_gate_uses_config_threshold_and_direction_aware_scale(monkeypatch):
    iff = pytest.importorskip("alpha_overlay.iff")
    FLOW = {"v": -0.6}
    monkeypatch.setattr(iff, "get_flow_score", lambda symbol, obi: FLOW["v"])
    monkeypatch.setattr(config, "IFF_VETO_THRESHOLD", 0.65, raising=False)
    assert iff.apply_iff_gate(0.5, "AAPL", 0.0)[2] is False       # 0.6 < 0.65
    monkeypatch.setattr(config, "IFF_VETO_THRESHOLD", 0.5, raising=False)
    assert iff.apply_iff_gate(0.5, "AAPL", 0.0)[2] is True

    monkeypatch.setattr(config, "IFF_SOFT_SCALE", 0.5, raising=False)
    FLOW["v"] = +0.3                                              # opposes a short
    gated, _, veto = iff.apply_iff_gate(-0.5, "AAPL", 0.0)
    assert not veto and abs(gated) < 0.5                          # was 0.575 (stronger)


def _engine_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    gm = pytest.importorskip("goals.goal_module")
    ms = pytest.importorskip("execution.market_session")
    iff = pytest.importorskip("alpha_overlay.iff")
    decision = mock.Mock(allowed=True, leverage=5.0, risk_budget_usd=25.0, reason="")
    monkeypatch.setattr(gm, "evaluate_trade", lambda *a, **k: decision)
    monkeypatch.setattr(ms, "is_market_session_open", lambda s: (True, "", None))
    monkeypatch.setattr(iff, "hold_and_evaluate_micro_buffer", lambda *a, **k: (False, "ok"))
    return iff


def _packet(direction, flow, veto=False):
    return {
        "signal_id": "sig_test", "instrument": "BTC-USD", "direction_magnitude": direction,
        "confidence_score": 0.6, "conviction_score": 0.6, "flow_score": flow, "iff_veto": veto,
        "dead_day_result": {"is_dead_day": False, "effective_conviction": 0.6,
                            "filter_mode": "Percentile P10"},
    }


def test_engine_consumes_gated_packet_and_flow_is_direction_aware(monkeypatch, tmp_path):
    from execution.engine import ExecutionEngine
    iff = _engine_env(monkeypatch, tmp_path)
    monkeypatch.setattr(iff, "get_flow_score",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("engine recomputed flow")))
    ee = ExecutionEngine()
    aligned = ee.size_order(_packet(-0.4, -0.3), {})              # short, bearish flow
    opposed = ee.size_order(_packet(-0.4, +0.3), {})              # short, bullish flow
    assert aligned["portfolio_allocation_pct"] > opposed["portfolio_allocation_pct"]
    assert aligned["decision_trace"]["iff_veto"] is False


def test_engine_partial_tp_fires_once(monkeypatch, tmp_path):
    from execution.engine import ExecutionEngine
    _engine_env(monkeypatch, tmp_path)
    profile = config.RISK_PROFILES[config.ACTIVE_RISK_PROFILE]
    pos = {"BTC-USD": {"side": "LONG", "exposure_pct": 0.1,
                       "unrealized_plpc": profile["PARTIAL_TP_THRESHOLD_PCT"] + 0.01}}
    ee = ExecutionEngine()
    first = ee.size_order(_packet(0.4, 0.0), pos)
    assert first and first["is_take_profit"] and first["close_fraction"] == profile["PARTIAL_TP_SELL_PCT"]
    pos["BTC-USD"]["partial_tp_done"] = True
    assert not (ee.size_order(_packet(0.4, 0.0), pos) or {}).get("is_take_profit")


# ── 5. LSTM final label ──────────────────────────────────────────────────────
def test_lstm_uses_shared_label_helper():
    m = pytest.importorskip("brain.models.lstm_model")
    src = inspect.getsource(m)
    assert "next_bar_labels" in src or "build_sequence_samples" in src


# ── 6. risk.py JSON path (fixture-free; fails on the original file) ──────────
def test_risk_recalibrate_reads_execution_store_json():
    from execution import risk as R
    assert hasattr(R, "json")
    trades = [{"realized_pnl": 5.0}] * 10                        # 10 wins, 0 losses
    with mock.patch.object(R.os.path, "exists", return_value=True), \
         mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(trades))):
        rg = R.RiskGuard()
        p_hat, _ = rg.recalibrate_kelly_parameters()              # trades_history=None → json.load path
    assert p_hat == pytest.approx(11 / 12, abs=1e-4)             # NameError used to be swallowed → 0.55


def test_risk_circuit_breaker_uses_live_equity_and_lets_exits_through():
    from execution.risk import RiskGuard
    rg = RiskGuard()
    rg.update_state(0.0, {}, current_equity=880.0)                # 12 % below the 1000 day-start
    entry = {"instrument": "BTC-USD", "action": "BUY", "confidence": 0.6,
             "portfolio_allocation_pct": 0.1, "is_take_profit": False}
    assert rg.check_order(entry)["failed_check"] == "circuit_breaker_active"
    rg.update_state(0.1, {"BTC-USD": {"side": "LONG", "exposure_pct": 0.1}}, current_equity=880.0)
    assert rg.check_order({**entry, "action": "SELL"})["risk_state"] == "APPROVED"
    assert rg.check_order({**entry, "action": "SELL", "is_take_profit": True})["risk_state"] == "APPROVED"


# ── 7. simulated OMS ATR stop calculations ───────────────────────────────────
def _oms(tmp_path, monkeypatch, positions=None):
    from execution.simulated_oms import SimulatedFuturesOMS
    oms = SimulatedFuturesOMS(state_file=str(tmp_path / "acct.json"))
    monkeypatch.setattr(oms, "_log_executions", lambda execs: None)
    oms._write_state({"equity": 1000.0, "balance": 1000.0, "realized_pl": 0.0,
                      "positions": positions or {}})
    return oms


def test_oms_initial_stop_is_atr_based(tmp_path, monkeypatch):
    ms = pytest.importorskip("execution.market_session")
    monkeypatch.setattr(ms, "is_market_session_open", lambda s: (True, "", None))
    oms = _oms(tmp_path, monkeypatch)
    order = {"instrument": "BTC-USD", "action": "BUY", "risk_state": "APPROVED",
             "portfolio_allocation_pct": 0.1, "dynamic_leverage": 5.0,
             "risk_budget_usd": 10.0, "atr": 900.0}
    out = oms.submit_order(order, 60000.0, obi_rho=0.0)
    stop = oms._read_state()["positions"]["BTC-USD"]["atr_trailing_stop"]
    assert stop == pytest.approx(out["price"] - 2.0 * 900.0, abs=1e-3)   # was fill * 0.98


def test_oms_trailing_stop_ratchets_then_triggers_once(tmp_path, monkeypatch):
    gm = pytest.importorskip("goals.goal_module")
    calls = []
    monkeypatch.setattr(gm, "record_trade_result", lambda ac, pnl: calls.append((ac, pnl)))
    if "SOL-USD" not in config.CRYPTO_INSTRUMENTS:
        monkeypatch.setattr(config, "CRYPTO_INSTRUMENTS", list(config.CRYPTO_INSTRUMENTS) + ["SOL-USD"])
    pos = {"SOL-USD": {"trade_id": "trd_t", "symbol": "SOL-USD", "qty": 1.0, "initial_qty": 1.0,
                       "entry_price": 100.0, "current_price": 100.0, "leverage": 5.0,
                       "atr_trailing_stop": 96.0, "opened_at": "2026-01-01T00:00:00Z"}}
    oms = _oms(tmp_path, monkeypatch, pos)
    oms.update_prices({"SOL-USD": 110.0}, {"SOL-USD": 2.0})
    st = oms._read_state()["positions"]["SOL-USD"]
    assert st["atr_trailing_stop"] == pytest.approx(106.0)               # max(96, 110 - 2*2)
    n_before = len(calls)                                                 # TP1 already fired at 110
    exits = oms.update_prices({"SOL-USD": 105.0}, {"SOL-USD": 2.0})      # 105 <= 106
    assert any(e["reason"] == "ATR_TRAILING_STOP" for e in exits)
    assert "SOL-USD" not in oms._read_state()["positions"]
    assert len(calls) - n_before == len(exits)                            # exactly one goal record per exit
    assert all(ac == "crypto" for ac, _ in calls)                         # SOL-USD is crypto, not "stock"


def test_oms_partial_tp_order_never_exceeds_position(tmp_path, monkeypatch):
    ms = pytest.importorskip("execution.market_session")
    monkeypatch.setattr(ms, "is_market_session_open", lambda s: (True, "", None))
    pos = {"AAPL": {"trade_id": "trd_a", "symbol": "AAPL", "qty": 0.3, "entry_price": 200.0,
                    "current_price": 200.0, "leverage": 5.0, "atr_trailing_stop": 190.0,
                    "opened_at": "2026-01-01T00:00:00Z"}}
    oms = _oms(tmp_path, monkeypatch, pos)
    tp = {"instrument": "AAPL", "action": "SELL", "risk_state": "APPROVED", "is_take_profit": True,
          "portfolio_allocation_pct": 0.05, "close_fraction": 0.5, "atr": 4.0}
    oms.submit_order(tp, 200.0, obi_rho=0.0)
    left = oms._read_state()["positions"]["AAPL"]["qty"]
    assert left == pytest.approx(0.15, abs=1e-6) and left > 0            # not flipped short


# ── extra regression tests for bugs found while reading engine.py / simulated_oms.py ──
def test_engine_does_not_pyramid_same_side(monkeypatch, tmp_path):
    """OMS reports side as LONG/SHORT but the engine compared it with BUY/SELL -> guard never fired."""
    from execution.engine import ExecutionEngine
    _engine_env(monkeypatch, tmp_path)
    ee = ExecutionEngine()
    held_long = {"BTC-USD": {"side": "LONG", "exposure_pct": 0.1, "unrealized_plpc": 0.0}}
    assert ee.size_order(_packet(+0.4, 0.0), held_long) is None          # already long: no add
    held_short = {"BTC-USD": {"side": "SHORT", "exposure_pct": 0.1, "unrealized_plpc": 0.0}}
    assert ee.size_order(_packet(-0.4, 0.0), held_short) is None
    assert ee.size_order(_packet(-0.4, 0.0), held_long)["action"] == "SELL"   # reversal still allowed


def test_engine_short_take_profit_buys_back(monkeypatch, tmp_path):
    """exposure_pct is always positive, so the old `SELL if exposure_pct > 0` sold MORE of a short."""
    from execution.engine import ExecutionEngine
    _engine_env(monkeypatch, tmp_path)
    thr = config.RISK_PROFILES[config.ACTIVE_RISK_PROFILE]["PARTIAL_TP_THRESHOLD_PCT"]
    pos = {"BTC-USD": {"side": "SHORT", "exposure_pct": 0.1, "unrealized_plpc": thr + 0.01}}
    order = ExecutionEngine().size_order(_packet(-0.4, 0.0), pos)
    assert order["is_take_profit"] and order["action"] == "BUY"


def test_oms_partial_close_reduces_qty_and_keeps_entry(tmp_path, monkeypatch):
    """Guards the partial-reduction branch (an `else:` there may fall through to the 'add' maths)."""
    ms = pytest.importorskip("execution.market_session")
    monkeypatch.setattr(ms, "is_market_session_open", lambda s: (True, "", None))
    pos = {"BTC-USD": {"trade_id": "trd_b", "symbol": "BTC-USD", "qty": 1.0, "initial_qty": 1.0,
                       "entry_price": 100.0, "current_price": 100.0, "leverage": 5.0,
                       "atr_trailing_stop": 90.0, "opened_at": "2026-01-01T00:00:00Z"}}
    oms = _oms(tmp_path, monkeypatch, pos)
    tp = {"instrument": "BTC-USD", "action": "SELL", "risk_state": "APPROVED", "is_take_profit": True,
          "portfolio_allocation_pct": 0.05, "close_fraction": 0.4, "atr": 2.0}
    oms.submit_order(tp, 110.0, obi_rho=0.0)
    p = oms._read_state()["positions"]["BTC-USD"]
    assert p["qty"] == pytest.approx(0.6, abs=1e-6)          # reduced by 40 %
    assert p["entry_price"] == pytest.approx(100.0)          # NOT blended with the 110 exit fill
    assert p.get("partial_tp_done") is True
