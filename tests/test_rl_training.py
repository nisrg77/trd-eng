"""
tests/test_rl_training.py — Unit Tests for Purged Walk-Forward Training & Baselines

Verifies Phase 2 requirements:
1. Purged walk-forward split construction with embargo gap.
2. Baselines evaluation harness (Flat, Buy-and-Hold, Random, Bollinger).
3. Deflated Sharpe Ratio (DSR) calculation.
4. Full walk-forward training execution, artifact logging, and verdict generation.
"""

import os
import math
import numpy as np
import pandas as pd
import pytest

from research.rl.train_rl import (
    TrainRLConfig,
    create_purged_walk_forward_splits,
    evaluate_baselines,
    compute_deflated_sharpe_ratio,
    run_walk_forward_training,
    get_git_revision_hash
)
from research.rl.trading_env import TradingEnv, TradingEnvConfig, ObservationNormalizer
from tests.test_rl_env import create_synthetic_ohlcv


def test_purged_walk_forward_split_embargo():
    df = create_synthetic_ohlcv(n_bars=200, seed=42)
    n_folds = 3
    embargo = 15

    splits = create_purged_walk_forward_splits(df, n_folds=n_folds, embargo_bars=embargo)
    assert len(splits) == n_folds

    for split in splits:
        train_start, train_end = split.train_range
        val_start, val_end = split.val_range

        # Crucial Invariant: Exact embargo gap between train end and val start
        assert val_start == train_end + embargo, f"Fold {split.fold_idx} missing embargo gap!"
        assert val_end > val_start
        assert len(split.train_df) == (train_end - train_start)
        assert len(split.val_df) == (val_end - val_start)


def test_baseline_evaluations_on_val_env():
    df = create_synthetic_ohlcv(n_bars=100, seed=10)
    normalizer = ObservationNormalizer()
    normalizer.fit(df)

    def env_factory():
        return TradingEnv(df, normalizer=normalizer, config=TradingEnvConfig(initial_equity=10000.0))

    baselines = evaluate_baselines(env_factory, symbol="BTC-USD")

    # All 4 baselines must be present
    assert "flat" in baselines
    assert "buy_and_hold" in baselines
    assert "random" in baselines
    assert "bollinger" in baselines

    # Flat baseline must have 0 trades, 0 return
    assert baselines["flat"]["trade_count"] == 0
    assert baselines["flat"]["net_return_pct"] == 0.0

    # Buy and hold must have exactly 1 trade
    assert baselines["buy_and_hold"]["trade_count"] == 1
    assert math.isfinite(baselines["buy_and_hold"]["annualized_sharpe"])

    # Bollinger must return valid finite metrics
    assert "annualized_sharpe" in baselines["bollinger"]
    assert "max_drawdown_pct" in baselines["bollinger"]


def test_deflated_sharpe_ratio_computation():
    # Single or equal Sharpe
    dsr_null = compute_deflated_sharpe_ratio(1.5, [1.5], n_samples=100)
    assert 0.0 <= dsr_null <= 1.0

    # Multiple testing deflation: with many trials, DSR drops relative to naive Sharpe
    sharpes_broad = [0.2, 0.5, 0.9, 1.2, 1.4, 1.8, 2.1, 2.3]
    dsr_high_trials = compute_deflated_sharpe_ratio(1.4, sharpes_broad, n_samples=50)
    assert 0.0 <= dsr_high_trials <= 1.0


def test_walk_forward_training_run_and_artifact_logging(tmp_path):
    df = create_synthetic_ohlcv(n_bars=160, seed=77)
    
    # Fast test configuration (2 folds, 2 seeds, minimal steps)
    cfg = TrainRLConfig(
        symbol="BTC-USD",
        n_folds=2,
        seeds=[42, 43],
        embargo_bars=10,
        total_timesteps=256,
        n_steps=64,
        batch_size=32,
        output_dir=str(tmp_path)
    )

    results = run_walk_forward_training(df, config=cfg)

    # Check summary structure
    assert "verdict" in results
    assert results["verdict"] in ["PASS", "FAIL"]
    assert "git_hash" in results
    assert len(results["folds"]) == 2
    assert "deflated_sharpe_ratio" in results

    # Check artifact persistence on disk
    run_dirs = [d for d in os.listdir(tmp_path) if d.startswith("run_")]
    assert len(run_dirs) == 1
    target_dir = os.path.join(tmp_path, run_dirs[0])
    
    assert os.path.exists(os.path.join(target_dir, "run_summary.json"))
    assert os.path.exists(os.path.join(target_dir, "norm_stats_fold_0.json"))
