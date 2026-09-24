"""
tests/test_rl_onnx_export.py — Unit Tests for ONNX Policy Export & Parity Verification

Verifies Phase 3 requirements:
1. Export of frozen ONNX model graph (model.onnx).
2. Emission of model_meta.json with complete provenance and schema hash.
3. Strict parity test: SB3 predict() vs. onnxruntime matches within tolerance on 1,000 random observations.
"""

import os
import json
import numpy as np
import pytest
from stable_baselines3 import PPO

from research.rl.trading_env import (
    TradingEnv,
    TradingEnvConfig,
    ObservationNormalizer,
    ALL_FEATURE_NAMES
)
from research.rl.export_onnx import (
    export_policy_to_onnx,
    verify_onnx_parity,
    compute_schema_hash
)
from tests.test_rl_env import create_synthetic_ohlcv


@pytest.fixture(scope="module")
def trained_sb3_fixture(tmp_path_factory):
    """Creates a quick trained SB3 PPO model for ONNX export testing."""
    tmp_dir = tmp_path_factory.mktemp("onnx_test")
    df = create_synthetic_ohlcv(n_bars=80, seed=42)
    normalizer = ObservationNormalizer()
    normalizer.fit(df)

    env = TradingEnv(df, normalizer=normalizer, config=TradingEnvConfig(initial_equity=10000.0))
    model = PPO(
        "MlpPolicy",
        env,
        n_steps=64,
        batch_size=32,
        gamma=0.99,
        seed=42,
        verbose=0
    )
    model.learn(total_timesteps=128)

    training_cfg = {"learning_rate": 3e-4, "n_steps": 64, "batch_size": 32}
    onnx_path, meta_path = export_policy_to_onnx(
        model=model,
        normalizer=normalizer,
        output_dir=str(tmp_dir),
        training_config=training_cfg,
        seed=42,
        data_date_range={"start": "2026-09-01", "end": "2026-09-05"},
        model_name="test_model"
    )

    return {
        "model": model,
        "normalizer": normalizer,
        "onnx_path": onnx_path,
        "meta_path": meta_path,
        "dir": str(tmp_dir)
    }


def test_onnx_export_file_and_metadata_structure(trained_sb3_fixture):
    onnx_path = trained_sb3_fixture["onnx_path"]
    meta_path = trained_sb3_fixture["meta_path"]

    # 1. Assert files exist
    assert os.path.exists(onnx_path)
    assert os.path.getsize(onnx_path) > 1000  # Valid binary ONNX graph

    assert os.path.exists(meta_path)
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # 2. Assert required metadata fields
    assert meta["model_name"] == "test_model"
    assert meta["feature_names"] == ALL_FEATURE_NAMES
    assert len(meta["feature_names"]) == 12
    assert "normalization_stats" in meta
    assert "git_hash" in meta
    assert meta["seed"] == 42
    assert meta["data_date_range"]["start"] == "2026-09-01"

    # 3. Assert feature schema hash integrity
    expected_hash = compute_schema_hash(ALL_FEATURE_NAMES)
    assert meta["feature_schema_hash"] == expected_hash
    assert len(meta["feature_schema_hash"]) == 16


def test_sb3_vs_onnxruntime_1000_samples_parity(trained_sb3_fixture):
    model = trained_sb3_fixture["model"]
    onnx_path = trained_sb3_fixture["onnx_path"]

    # Rigorous 1,000-sample parity test
    passed, max_diff = verify_onnx_parity(
        model=model,
        onnx_path=onnx_path,
        n_samples=1000,
        tolerance=1e-4,
        seed=42
    )

    assert passed is True, f"ONNX parity failed! Max logit difference: {max_diff}"
    assert max_diff <= 1e-4
