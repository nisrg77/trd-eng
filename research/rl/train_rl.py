"""
research/rl/train_rl.py — Purged Walk-Forward PPO Training & Baseline Benchmarking

Features:
1. Purged Walk-Forward Splits with an embargo gap to prevent information leakage.
2. Trains N=5 seeds per fold with Stable-Baselines3 PPO on the custom TradingEnv.
3. Rigorous Baseline Benchmarking on identical validation windows with identical costs:
   - Flat Policy
   - Buy-and-Hold
   - Random Policy
   - BollingerReversionStrategy
4. Comprehensive Metrics Reporting:
   - Net return, Sharpe ratio, Max drawdown, Turnover, Trade count.
   - Seed dispersion (standard deviation across seeds).
   - Deflated Sharpe Ratio (DSR) accounting for multiple testing.
5. Configurable PASS/FAIL verdict:
   - Beats all baselines net of costs in at least X of Y folds AND positive across a majority of seeds.
6. Local Run Artifact Logging (config, metrics, git hash, seeds, verdict).
"""

from __future__ import annotations
import os
import sys
import json
import time
import math
import random
import logging
import subprocess
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple, Callable

import numpy as np
import pandas as pd
import scipy.stats as stats
import torch
from stable_baselines3 import PPO

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from research.rl.trading_env import (
    TradingEnv,
    TradingEnvConfig,
    ObservationNormalizer,
    prepare_market_features
)
from execution.cost_model import CostModelConfig
from core.order_intent import OrderSide, PositionContext
from strategies.crypto.bollinger_reversion import BollingerReversionStrategy
from research.rl.quant_strategy_bridge import QuantStrategyBridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s [TRAIN_RL] %(levelname)s %(message)s")
log = logging.getLogger(__name__)


@dataclass
class TrainRLConfig:
    symbol: str = "BTC-USD"
    n_folds: int = 3
    seeds: List[int] = field(default_factory=lambda: [42, 43, 44, 45, 46])
    embargo_bars: int = 20
    total_timesteps: int = 3000
    learning_rate: float = 3e-4
    n_steps: int = 128
    batch_size: int = 64
    min_holding_bars: int = 3
    min_folds_beat_baselines: int = 2
    output_dir: str = "research/rl/runs"
    initial_equity: float = 10000.0


@dataclass
class FoldSplit:
    fold_idx: int
    train_df: pd.DataFrame
    val_df: pd.DataFrame
    train_range: Tuple[int, int]
    val_range: Tuple[int, int]


def get_git_revision_hash() -> str:
    """Retrieves current Git commit hash for provenance."""
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("ascii").strip()
    except Exception:
        return "unknown_git_hash"


def create_purged_walk_forward_splits(
    df: pd.DataFrame,
    n_folds: int = 3,
    embargo_bars: int = 20,
    min_train_ratio: float = 0.5
) -> List[FoldSplit]:
    """
    Constructs walk-forward folds with an embargo gap between train and validation.
    """
    n_total = len(df)
    train_size = int(n_total * min_train_ratio)
    remaining_bars = n_total - train_size - (n_folds * embargo_bars)
    val_size = max(30, remaining_bars // n_folds)

    splits = []
    for k in range(n_folds):
        train_start = 0
        train_end = train_size + (k * val_size)
        val_start = train_end + embargo_bars
        val_end = min(n_total, val_start + val_size)

        if val_start >= n_total or val_end <= val_start:
            break

        train_df = df.iloc[train_start:train_end].copy().reset_index(drop=True)
        val_df = df.iloc[val_start:val_end].copy().reset_index(drop=True)

        splits.append(FoldSplit(
            fold_idx=k,
            train_df=train_df,
            val_df=val_df,
            train_range=(train_start, train_end),
            val_range=(val_start, val_end)
        ))

    return splits


# ── Policy & Baseline Evaluation Harness ─────────────────────────────────────
def evaluate_policy_on_env(env: TradingEnv, predict_fn: Callable[[np.ndarray], int]) -> Dict[str, Any]:
    """
    Evaluates an arbitrary policy function step-by-step on a TradingEnv,
    measuring performance under identical transaction costs.
    """
    obs, info = env.reset()
    r_steps: List[float] = []
    positions: List[float] = [info["position"]]
    equities: List[float] = [info["equity"]]

    done = False
    while not done:
        action = predict_fn(obs)
        obs, reward, terminated, truncated, step_info = env.step(action)
        r_steps.append(step_info["r_step"] - step_info["cost_rate"])
        positions.append(step_info["position"])
        equities.append(step_info["equity"])
        done = terminated or truncated

    r_arr = np.array(r_steps)
    initial_eq = env.config.initial_equity
    final_eq = equities[-1]
    net_return_pct = ((final_eq / initial_eq) - 1.0) * 100.0

    # Sharpe calculation
    mean_ret = float(np.mean(r_arr)) if len(r_arr) > 0 else 0.0
    std_ret = float(np.std(r_arr)) if len(r_arr) > 0 else 1.0
    # Annualization factor for hourly bars (24 * 365)
    ann_sharpe = float((mean_ret / (std_ret + 1e-9)) * np.sqrt(24 * 365))

    # Max Drawdown
    eq_arr = np.array(equities)
    peaks = np.maximum.accumulate(eq_arr)
    dds = (peaks - eq_arr) / peaks
    max_dd_pct = float(np.max(dds)) * 100.0

    # Turnover
    turnover = float(np.sum(np.abs(np.diff(positions))))

    return {
        "net_return_pct": round(net_return_pct, 2),
        "annualized_sharpe": round(ann_sharpe, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "turnover": round(turnover, 2),
        "trade_count": env.trade_count,
        "total_costs_usd": round(env.total_costs_usd, 2),
        "final_equity": round(final_eq, 2),
        "r_steps": r_arr
    }


def evaluate_baselines(env_factory: Callable[[], TradingEnv], symbol: str) -> Dict[str, Dict[str, Any]]:
    """
    Evaluates all 4 standard baselines on the validation window:
    1. Flat Policy (always action 1)
    2. Buy and Hold (action 2)
    3. Random Policy (random uniform action)
    4. Bollinger Reversion Strategy
    """
    baselines = {}

    # 1. Flat Baseline
    baselines["flat"] = evaluate_policy_on_env(env_factory(), lambda obs: 1)

    # 2. Buy and Hold Baseline
    baselines["buy_and_hold"] = evaluate_policy_on_env(env_factory(), lambda obs: 2)

    # 3. Random Baseline (deterministic seed)
    rng = random.Random(42)
    baselines["random"] = evaluate_policy_on_env(env_factory(), lambda obs: rng.choice([0, 1, 2]))

    # 4. Bollinger Reversion Baseline
    boll = BollingerReversionStrategy(strategy_id="boll_bench", sleeve_id="sleeve_bench")
    env_boll = env_factory()
    obs_b, info_b = env_boll.reset()
    
    last_act = 1
    def bollinger_policy(obs: np.ndarray) -> int:
        nonlocal last_act
        step_idx = env_boll.current_step
        df_sub = env_boll.df.iloc[:step_idx + 1]
        pos = env_boll.current_position
        pos_ctx = PositionContext(
            symbol=symbol,
            qty=pos,
            entry_price=env_boll.entry_price,
            mark_price=float(df_sub.iloc[-1]["close"]),
            unrealized_pnl=0.0,
            opened_at_epoch=0.0
        )
        intent = boll.evaluate(symbol, df_sub, position_context=pos_ctx if abs(pos) > 1e-7 else None)
        if intent:
            if intent.legs[0].side == OrderSide.BUY:
                last_act = 2
            elif intent.legs[0].side == OrderSide.SELL:
                last_act = 1  # Exit to flat
        return last_act

    baselines["bollinger"] = evaluate_policy_on_env(env_boll, bollinger_policy)

    # 5. Dual Thrust Baseline
    env_dt = env_factory()
    dt_sigs = QuantStrategyBridge.dual_thrust_signals(env_dt.df)
    def dt_policy(obs: np.ndarray) -> int:
        idx = min(env_dt.current_step, len(dt_sigs) - 1)
        sig = dt_sigs.iloc[idx]
        return 2 if sig > 0 else (0 if sig < 0 else 1)
    baselines["dual_thrust"] = evaluate_policy_on_env(env_dt, dt_policy)

    # 6. Awesome Oscillator Baseline
    env_ao = env_factory()
    ao_sigs = QuantStrategyBridge.awesome_oscillator_signals(env_ao.df)
    def ao_policy(obs: np.ndarray) -> int:
        idx = min(env_ao.current_step, len(ao_sigs) - 1)
        sig = ao_sigs.iloc[idx]
        return 2 if sig > 0 else (0 if sig < 0 else 1)
    baselines["awesome_oscillator"] = evaluate_policy_on_env(env_ao, ao_policy)

    # 7. Heikin-Ashi Baseline
    env_ha = env_factory()
    ha_sigs = QuantStrategyBridge.heikin_ashi_signals(env_ha.df)
    def ha_policy(obs: np.ndarray) -> int:
        idx = min(env_ha.current_step, len(ha_sigs) - 1)
        sig = ha_sigs.iloc[idx]
        return 2 if sig > 0 else (0 if sig < 0 else 1)
    baselines["heikin_ashi"] = evaluate_policy_on_env(env_ha, ha_policy)

    # 8. RSI Pattern Baseline
    env_rsi = env_factory()
    rsi_sigs = QuantStrategyBridge.rsi_pattern_signals(env_rsi.df)
    def rsi_policy(obs: np.ndarray) -> int:
        idx = min(env_rsi.current_step, len(rsi_sigs) - 1)
        sig = rsi_sigs.iloc[idx]
        return 2 if sig > 0 else (0 if sig < 0 else 1)
    baselines["rsi_pattern"] = evaluate_policy_on_env(env_rsi, rsi_policy)

    return baselines


def compute_deflated_sharpe_ratio(
    sharpe: float,
    all_sharpes: List[float],
    n_samples: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0
) -> float:
    """
    Computes Bailey & López de Prado (2014) Deflated Sharpe Ratio (DSR)
    correcting for data snooping / multiple seed trials.
    """
    n_trials = max(1, len(all_sharpes))
    if n_trials <= 1 or n_samples <= 1:
        return 0.50

    var_sr = np.var(all_sharpes, ddof=1) if len(all_sharpes) > 1 else 0.01
    std_sr = np.sqrt(max(1e-6, var_sr))

    # Expected maximum Sharpe ratio under the null hypothesis (Euler-Mascheroni approximation)
    em_c = 0.5772156649
    z_max = (1.0 - em_c) * stats.norm.ppf(1.0 - 1.0 / n_trials) + em_c * stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    sr_star = std_sr * z_max

    # Standard error of Sharpe with non-normality correction
    denom = 1.0 - skewness * sharpe + ((kurtosis - 1.0) / 4.0) * (sharpe ** 2)
    denom = max(1e-6, denom)
    sigma_sr = np.sqrt(denom / (n_samples - 1))

    dsr = stats.norm.cdf((sharpe - sr_star) / max(1e-6, sigma_sr))
    return float(round(dsr, 4))


# ── Main Walk-Forward Training Coordinator ────────────────────────────────────
def run_walk_forward_training(
    df: pd.DataFrame,
    config: Optional[TrainRLConfig] = None
) -> Dict[str, Any]:
    """
    Coordinates walk-forward PPO training, baseline benchmarking, and provenance logging.
    """
    cfg = config or TrainRLConfig()
    git_hash = get_git_revision_hash()
    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(cfg.output_dir, f"run_{timestamp_str}")
    os.makedirs(run_dir, exist_ok=True)

    log.info("Starting Walk-Forward Training on %s (%d folds, %d seeds)...", cfg.symbol, cfg.n_folds, len(cfg.seeds))
    splits = create_purged_walk_forward_splits(df, n_folds=cfg.n_folds, embargo_bars=cfg.embargo_bars)

    fold_reports = []
    all_rl_sharpes: List[float] = []
    folds_beating_all_baselines = 0
    seeds_positive_count = 0
    total_seed_evals = 0

    for split in splits:
        log.info(
            "--- Processing Fold %d (Train: %d bars, Val: %d bars, Embargo: %d bars) ---",
            split.fold_idx, len(split.train_df), len(split.val_df), cfg.embargo_bars
        )

        # 1. Fit Normalizer strictly on Train split
        normalizer = ObservationNormalizer()
        normalizer.fit(prepare_market_features(split.train_df))
        norm_file = os.path.join(run_dir, f"norm_stats_fold_{split.fold_idx}.json")
        normalizer.save(norm_file)

        env_cfg = TradingEnvConfig(
            initial_equity=cfg.initial_equity,
            min_holding_bars=cfg.min_holding_bars
        )

        def make_val_env():
            return TradingEnv(split.val_df, normalizer=normalizer, config=env_cfg)

        # 2. Evaluate Baselines on Validation split
        baseline_results = evaluate_baselines(make_val_env, cfg.symbol)
        max_baseline_sharpe = max(b["annualized_sharpe"] for b in baseline_results.values())
        max_baseline_return = max(b["net_return_pct"] for b in baseline_results.values())

        # 3. Train N Seeds with PPO
        seed_results = []
        for seed in cfg.seeds:
            # Seed all RNGs
            random.seed(seed)
            np.random.seed(seed)
            torch.manual_seed(seed)

            train_env = TradingEnv(split.train_df, normalizer=normalizer, config=env_cfg)
            
            # Policy architecture
            policy_kwargs = dict(net_arch=dict(pi=[64, 64], vf=[64, 64]))
            model = PPO(
                "MlpPolicy",
                train_env,
                learning_rate=cfg.learning_rate,
                n_steps=cfg.n_steps,
                batch_size=cfg.batch_size,
                gamma=0.99,
                policy_kwargs=policy_kwargs,
                seed=seed,
                verbose=0
            )

            # Train offline
            model.learn(total_timesteps=cfg.total_timesteps)

            # Evaluate on Val Env
            val_env = make_val_env()
            eval_metrics = evaluate_policy_on_env(
                val_env,
                lambda obs: int(model.predict(obs, deterministic=True)[0])
            )
            eval_metrics["seed"] = seed
            all_rl_sharpes.append(eval_metrics["annualized_sharpe"])
            total_seed_evals += 1
            if eval_metrics["net_return_pct"] > 0.0:
                seeds_positive_count += 1

            seed_results.append(eval_metrics)

        # Fold Aggregations
        sharpes = [s["annualized_sharpe"] for s in seed_results]
        returns = [s["net_return_pct"] for s in seed_results]
        mean_sharpe = float(np.mean(sharpes))
        std_sharpe = float(np.std(sharpes))
        mean_return = float(np.mean(returns))

        # Check if fold beats baselines
        fold_beats_baselines = bool((mean_sharpe > max_baseline_sharpe) and (mean_return > max_baseline_return))
        if fold_beats_baselines:
            folds_beating_all_baselines += 1

        fold_reports.append({
            "fold_idx": split.fold_idx,
            "train_range": split.train_range,
            "val_range": split.val_range,
            "mean_sharpe": round(mean_sharpe, 2),
            "std_sharpe_dispersion": round(std_sharpe, 2),
            "mean_net_return_pct": round(mean_return, 2),
            "fold_beats_all_baselines": fold_beats_baselines,
            "baselines": {
                name: {
                    "net_return_pct": b["net_return_pct"],
                    "annualized_sharpe": b["annualized_sharpe"],
                    "max_drawdown_pct": b["max_drawdown_pct"],
                    "trade_count": b["trade_count"]
                }
                for name, b in baseline_results.items()
            },
            "seeds": [
                {
                    "seed": s["seed"],
                    "net_return_pct": s["net_return_pct"],
                    "annualized_sharpe": s["annualized_sharpe"],
                    "max_drawdown_pct": s["max_drawdown_pct"],
                    "trade_count": s["trade_count"]
                }
                for s in seed_results
            ]
        })

    # Global Deflated Sharpe Ratio
    global_mean_sharpe = float(np.mean(all_rl_sharpes)) if all_rl_sharpes else 0.0
    dsr = compute_deflated_sharpe_ratio(
        global_mean_sharpe,
        all_rl_sharpes,
        n_samples=len(df) // cfg.n_folds
    )

    # 4. PASS/FAIL Verdict
    majority_positive = bool((seeds_positive_count / max(1, total_seed_evals)) >= 0.50)
    beats_folds_target = bool(folds_beating_all_baselines >= cfg.min_folds_beat_baselines)
    verdict = "PASS" if (beats_folds_target and majority_positive) else "FAIL"

    summary_result = {
        "verdict": verdict,
        "git_hash": git_hash,
        "timestamp": timestamp_str,
        "config": asdict(cfg),
        "folds_beating_baselines": f"{folds_beating_all_baselines}/{len(splits)}",
        "seeds_positive_ratio": f"{seeds_positive_count}/{total_seed_evals}",
        "global_mean_sharpe": round(global_mean_sharpe, 2),
        "deflated_sharpe_ratio": dsr,
        "folds": fold_reports
    }

    # Save artifacts to run directory
    with open(os.path.join(run_dir, "run_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary_result, f, indent=2, default=str)

    log.info(
        "Walk-Forward Complete. Verdict: %s | Folds beating baselines: %s | DSR: %.4f",
        verdict, summary_result["folds_beating_baselines"], dsr
    )
    return summary_result


if __name__ == "__main__":
    from tests.test_rl_env import create_synthetic_ohlcv
    df_sample = create_synthetic_ohlcv(n_bars=300, seed=42)
    run_walk_forward_training(df_sample)
