"""
tests/test_rl_shadow_plugin.py — Tests for Phase 4 ONNX Policy Plugin & Shadow Mode
"""

import os
import json
import time
import pytest
import numpy as np
import pandas as pd
import onnxruntime as ort

from strategies.ai.onnx_policy_plugin import (
    ONNXPolicyPlugin,
    ShadowPnLTracker,
    compute_live_schema_hash,
    EXPECTED_FEATURE_NAMES
)
from core.decision_trace import decision_trace_buffer
from core.order_intent import PositionContext, OrderSide
from data_pipeline.feature_standardizer import compute_standard_features
from research.rl.trading_env import prepare_market_features, TradingEnv, TradingEnvConfig, ObservationNormalizer
from research.rl.export_onnx import export_policy_to_onnx
from stable_baselines3 import PPO


@pytest.fixture(scope="module")
def exported_onnx_bundle(tmp_path_factory):
    """Trains a quick mini model and exports ONNX for testing."""
    tmp_dir = str(tmp_path_factory.mktemp("rl_test_plugin"))
    np.random.seed(42)
    n = 100
    dates = pd.date_range("2026-01-01", periods=n, freq="1h")
    p = 50000.0 + np.cumsum(np.random.randn(n) * 100.0)
    df = pd.DataFrame({
        "timestamp": dates.astype(int) // 10**9,
        "open": p + np.random.randn(n) * 10,
        "high": p + 50 + np.random.rand(n) * 20,
        "low": p - 50 - np.random.rand(n) * 20,
        "close": p,
        "volume": np.random.rand(n) * 100 + 10
    })

    normalizer = ObservationNormalizer()
    normalizer.fit(df)
    env = TradingEnv(df, normalizer=normalizer, config=TradingEnvConfig(initial_equity=10000.0))
    model = PPO("MlpPolicy", env, n_steps=64, batch_size=32, verbose=0, seed=42)
    model.learn(total_timesteps=128)

    onnx_path, meta_path = export_policy_to_onnx(
        model=model,
        normalizer=normalizer,
        output_dir=tmp_dir,
        training_config={"learning_rate": 3e-4},
        seed=42,
        model_name="test_policy"
    )

    return onnx_path, meta_path, df


def test_schema_hash_gate(exported_onnx_bundle, tmp_path):
    onnx_path, meta_path, df = exported_onnx_bundle

    # Valid load passes
    plugin = ONNXPolicyPlugin(
        strategy_id="ai_test_01",
        onnx_model_path=onnx_path,
        meta_path=meta_path,
        shadow_mode=True
    )
    assert plugin.is_loaded is True

    # Tampered schema hash fails with ValueError and alert
    bad_meta_path = str(tmp_path / "bad_meta.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta_data = json.load(f)
    meta_data["feature_schema_hash"] = "tampered_hash_123"
    with open(bad_meta_path, "w", encoding="utf-8") as f:
        json.dump(meta_data, f)

    with pytest.raises(ValueError, match="CRITICAL SCHEMA MISMATCH"):
        ONNXPolicyPlugin(
            strategy_id="ai_bad_01",
            onnx_model_path=onnx_path,
            meta_path=bad_meta_path
        )


def test_shadow_mode_never_routes_orders(exported_onnx_bundle):
    onnx_path, meta_path, df = exported_onnx_bundle
    decision_trace_buffer.clear()

    plugin = ONNXPolicyPlugin(
        strategy_id="ai_shadow_test",
        onnx_model_path=onnx_path,
        meta_path=meta_path,
        shadow_mode=True
    )

    # In live engine, data_pipeline feeds pre-standardized DataFrame
    df_feat = compute_standard_features(df.iloc[:50].copy())

    # Warmup call
    plugin.evaluate("BTC-USD", df_feat)

    t0 = time.perf_counter()
    intent = plugin.evaluate("BTC-USD", df_feat)
    total_lat_ms = (time.perf_counter() - t0) * 1000.0

    # Invariant 1: Total execution and pure model inference are well within real-time limits
    assert total_lat_ms < 150.0

    # Invariant 2: Shadow mode returns None (NEVER reaches execution router)
    assert intent is None

    # Invariant 3: Shadow signal is logged to decision trace with tag "rl_shadow"
    traces = decision_trace_buffer.get_recent_traces(limit=10)
    assert len(traces) >= 1
    recent = traces[-1]
    assert recent["simulated_latency_ms"] < 30.0  # Pure ONNX CPU inference is < 1ms
    assert recent["strategy_id"] == "ai_shadow_test"
    assert recent["final_action"] == "SHADOW_LOGGED"
    assert recent["shadow_meta_label"] in [0, 1, 2]
    assert 0.0 <= recent["shadow_meta_probability"] <= 1.0


def test_shadow_pnl_tracker():
    tracker = ShadowPnLTracker(initial_equity=10000.0)
    
    # Step 1: Open Long
    rec1 = tracker.record_shadow_step(
        symbol="BTC-USD",
        target_action=2, # Long
        current_price=50000.0,
        atr=500.0,
        timestamp=1000.0
    )
    assert tracker.trades_count == 1
    assert tracker.current_position == 1.0
    assert rec1["cost_usd"] > 0.0

    # Step 2: Price goes up 2% -> Profit
    rec2 = tracker.record_shadow_step(
        symbol="BTC-USD",
        target_action=2,
        current_price=51000.0,
        atr=500.0,
        timestamp=1060.0
    )
    assert tracker.equity > 10000.0

    # Step 3: Exit to flat
    rec3 = tracker.record_shadow_step(
        symbol="BTC-USD",
        target_action=1, # Flat
        current_price=51000.0,
        atr=500.0,
        timestamp=1120.0
    )
    assert tracker.current_position == 0.0
    summary = tracker.get_summary()
    assert summary["trades_count"] == 2
    assert summary["total_return_pct"] > 0.0
