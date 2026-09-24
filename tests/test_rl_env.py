"""
tests/test_rl_env.py — Unit Tests for Cost-Aware Gymnasium Trading Environment

Verifies all Phase 1 invariants:
1. No-lookahead test: Altering future data must NEVER alter past observations.
2. Cost accounting test: Exact verification of fees, spread, and ATR slippage.
3. Flat policy test: Pure flat action sequence yields reward exactly 0.0.
4. Fixed action sequence test: Hand-computed step-by-step PnL matches env output.
"""

import math
import numpy as np
import pandas as pd
import pytest

from execution.cost_model import CostModel, CostModelConfig
from research.rl.trading_env import (
    TradingEnv,
    TradingEnvConfig,
    ObservationNormalizer,
    prepare_market_features,
    ALL_FEATURE_NAMES,
    MARKET_FEATURE_NAMES
)


def create_synthetic_ohlcv(n_bars: int = 80, start_price: float = 100.0, seed: int = 42) -> pd.DataFrame:
    """Generates deterministic OHLCV test data."""
    np.random.seed(seed)
    timestamps = pd.date_range("2026-09-01", periods=n_bars, freq="1h")
    returns = np.random.normal(0.0005, 0.01, n_bars)
    prices = [start_price]
    for r in returns[1:]:
        prices.append(prices[-1] * (1.0 + r))
    
    prices = np.array(prices)
    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": prices * 0.999,
        "high": prices * 1.005,
        "low": prices * 0.995,
        "close": prices,
        "volume": np.random.uniform(500, 2000, n_bars)
    })
    return df


def test_no_lookahead_invariant():
    """
    Modifying future data (bars after step T) must NOT change the observation at step T.
    """
    df_base = create_synthetic_ohlcv(n_bars=80, seed=123)
    
    # Create altered dataframe where future data (bars 50+) is drastically modified
    df_altered = df_base.copy()
    cutoff = 50
    df_altered.loc[cutoff:, "close"] = df_altered.loc[cutoff:, "close"] * 5.0
    df_altered.loc[cutoff:, "high"] = df_altered.loc[cutoff:, "high"] * 5.0
    df_altered.loc[cutoff:, "low"] = df_altered.loc[cutoff:, "low"] * 5.0
    df_altered.loc[cutoff:, "open"] = df_altered.loc[cutoff:, "open"] * 5.0

    normalizer = ObservationNormalizer()
    normalizer.fit(prepare_market_features(df_base.iloc[:cutoff]))

    env1 = TradingEnv(df_base, normalizer=normalizer)
    env2 = TradingEnv(df_altered, normalizer=normalizer)

    obs1, _ = env1.reset()
    obs2, _ = env2.reset()

    # Step up to the cutoff bar
    for step_idx in range(cutoff - 25):
        # Observations at past and current bar must be identical
        np.testing.assert_allclose(
            obs1, obs2, rtol=1e-5, atol=1e-5,
            err_msg=f"Lookahead leak detected at step {step_idx}!"
        )
        obs1, _, _, _, _ = env1.step(1)  # Flat
        obs2, _, _, _, _ = env2.step(1)  # Flat


def test_flat_policy_reward_exactly_zero():
    """
    A policy that remains flat must earn reward exactly 0.0 at every step.
    """
    df = create_synthetic_ohlcv(n_bars=60, seed=42)
    normalizer = ObservationNormalizer()
    normalizer.fit(prepare_market_features(df))

    cfg = TradingEnvConfig(initial_equity=10000.0)
    env = TradingEnv(df, normalizer=normalizer, config=cfg)

    obs, info = env.reset()
    assert info["position"] == 0.0

    done = False
    step_count = 0
    while not done:
        obs, reward, terminated, truncated, info = env.step(1)  # 1 = FLAT
        assert reward == 0.0, f"Flat policy earned non-zero reward {reward} at step {step_count}!"
        assert info["equity"] == 10000.0
        assert info["drawdown"] == 0.0
        assert info["trade_count"] == 0
        done = terminated or truncated
        step_count += 1

    assert step_count > 20


def test_cost_accounting_verification():
    """
    Verifies that transaction costs match the CostModel calculations exactly.
    """
    df = create_synthetic_ohlcv(n_bars=50, seed=77)
    cost_cfg = CostModelConfig(
        taker_fee_bps=4.0,       # 0.0004
        spread_bps=2.0,          # 0.0002 -> 0.0001 half-spread
        slippage_atr_ratio=0.05
    )
    env_cfg = TradingEnvConfig(
        cost_config=cost_cfg,
        min_holding_bars=1,
        drawdown_penalty_weight=0.0,
        turnover_penalty_weight=0.0
    )
    env = TradingEnv(df, config=env_cfg)
    env.reset()

    # Step 1: Transition from 0.0 to 1.0 (LONG)
    curr_step = env.current_step
    next_open = float(env.df.iloc[curr_step + 1]["open"])
    atr_t = float(env.df.iloc[curr_step]["atr_14"])

    obs, reward, _, _, info = env.step(2)  # 2 = LONG

    expected_cost_rate = (4.0 * 1e-4) + (1.0 * 1e-4) + (0.05 * (atr_t / next_open))
    assert math.isclose(info["cost_rate"], expected_cost_rate, rel_tol=1e-5)
    assert info["position"] == 1.0

    # Step 2: Holding same position -> cost must be 0.0
    obs, reward, _, _, info2 = env.step(2)  # 2 = HOLD LONG
    assert info2["cost_rate"] == 0.0
    assert info2["position"] == 1.0


def test_fixed_action_sequence_hand_computed_pnl():
    """
    Executes a fixed action sequence and asserts step-by-step match with hand calculation.
    """
    df = create_synthetic_ohlcv(n_bars=40, seed=99)
    cost_cfg = CostModelConfig(taker_fee_bps=0.0, spread_bps=0.0, slippage_atr_ratio=0.0)
    env_cfg = TradingEnvConfig(
        cost_config=cost_cfg,
        min_holding_bars=1,
        drawdown_penalty_weight=0.0,
        turnover_penalty_weight=0.0
    )
    env = TradingEnv(df, config=env_cfg)
    env.reset()

    # Step 0 to 1: Enter LONG
    t0 = env.current_step
    c0 = float(env.df.iloc[t0]["close"])
    o1 = float(env.df.iloc[t0 + 1]["open"])
    c1 = float(env.df.iloc[t0 + 1]["close"])

    _, r1, _, _, _ = env.step(2)  # Enter Long
    # Held old (flat) from c0 to o1 -> return 0
    # Held new (long) from o1 to c1 -> return ln(c1 / o1)
    expected_r1 = np.log(c1 / o1)
    assert math.isclose(r1, expected_r1, rel_tol=1e-5)

    # Step 1 to 2: Hold LONG
    c2 = float(env.df.iloc[t0 + 2]["close"])
    _, r2, _, _, _ = env.step(2)  # Hold Long
    # Position maintained -> return ln(c2 / c1)
    expected_r2 = np.log(c2 / c1)
    assert math.isclose(r2, expected_r2, rel_tol=1e-5)

    # Step 2 to 3: Exit to FLAT
    o3 = float(env.df.iloc[t0 + 3]["open"])
    _, r3, _, _, _ = env.step(1)  # Exit to Flat
    # Held old (long) from c2 to o3 -> return ln(o3 / c2)
    # Held new (flat) from o3 to c3 -> return 0
    expected_r3 = np.log(o3 / c2)
    assert math.isclose(r3, expected_r3, rel_tol=1e-5)
