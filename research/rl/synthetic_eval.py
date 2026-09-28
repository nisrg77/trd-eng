"""
research/rl/synthetic_eval.py — Synthetic-Path Robustness Evaluation & Fidelity Gate

Tasks 6.1 - 6.3:
1. Block bootstrap and regime-resampled synthetic path generators preserving empirical market dynamics.
2. Rigorous Fidelity Gate checking fat tails (excess kurtosis), volatility clustering (autocorrelation of |returns|),
   and volume-volatility correlation.
3. Post-hoc evaluation of trained policies on synthetic paths under identical cost models,
   reporting median Sharpe, worst-decile drawdown, and turnover stability.
   INVARIANT 7: Out of scope for signal generation; never added to train_df.
"""

from __future__ import annotations
import math
import logging
from typing import Dict, Any, List, Optional, Tuple, Callable

import numpy as np
import pandas as pd
import scipy.stats as stats

from research.rl.trading_env import TradingEnv, TradingEnvConfig, ObservationNormalizer, prepare_market_features
from research.rl.train_rl import evaluate_policy_on_env

log = logging.getLogger(__name__)


# ── Task 6.1: Stationary Block Bootstrap & Regime Resampling ──────────────────

def generate_block_bootstrap_paths(
    df: pd.DataFrame,
    block_size: int = 24,
    n_paths: int = 10,
    seed: int = 42
) -> List[pd.DataFrame]:
    """
    Constructs synthetic OHLCV paths via stationary block bootstrap.
    Preserves intraday return correlation, vol clustering, and volume relationships.
    """
    rng = np.random.RandomState(seed)
    n_bars = len(df)
    if n_bars < block_size * 2:
        return [df.copy() for _ in range(n_paths)]

    close = df["close"].values
    log_rets = np.log(close[1:] / close[:-1])
    vol = df["volume"].values[1:]
    high_low_ratio = (df["high"].values[1:] / df["low"].values[1:])
    open_close_ratio = (df["open"].values[1:] / df["close"].values[1:])

    paths = []
    n_steps = n_bars - 1
    p_exit = 1.0 / block_size

    for p_idx in range(n_paths):
        resampled_rets = []
        resampled_vols = []
        resampled_hl = []
        resampled_oc = []

        curr_idx = rng.randint(0, len(log_rets))
        for _ in range(n_steps):
            resampled_rets.append(log_rets[curr_idx])
            resampled_vols.append(vol[curr_idx])
            resampled_hl.append(high_low_ratio[curr_idx])
            resampled_oc.append(open_close_ratio[curr_idx])

            # Transition: continue block with prob 1 - p_exit, else jump
            if rng.rand() < p_exit:
                curr_idx = rng.randint(0, len(log_rets))
            else:
                curr_idx = (curr_idx + 1) % len(log_rets)

        # Reconstruct price series
        init_px = float(df["close"].iloc[0])
        px_series = init_px * np.exp(np.cumsum(np.insert(resampled_rets, 0, 0.0)))
        vol_series = np.insert(resampled_vols, 0, df["volume"].iloc[0])
        hl_arr = np.insert(resampled_hl, 0, df["high"].iloc[0] / df["low"].iloc[0])
        oc_arr = np.insert(resampled_oc, 0, df["open"].iloc[0] / df["close"].iloc[0])

        syn_df = pd.DataFrame({
            "timestamp": df["timestamp"].values if "timestamp" in df.columns else np.arange(len(px_series)),
            "open": px_series * oc_arr,
            "high": px_series * np.sqrt(hl_arr),
            "low": px_series / np.sqrt(hl_arr),
            "close": px_series,
            "volume": vol_series
        })
        # Ensure high >= max(open, close) and low <= min(open, close)
        syn_df["high"] = np.maximum(syn_df["high"], np.maximum(syn_df["open"], syn_df["close"]))
        syn_df["low"] = np.minimum(syn_df["low"], np.minimum(syn_df["open"], syn_df["close"]))
        paths.append(syn_df)

    return paths


# ── Task 6.2: Stylized Facts Fidelity Gate ────────────────────────────────────

class FidelityGate:
    """
    Enforces that synthetic paths reproduce critical empirical stylized facts:
    1. Fat Tails: Excess kurtosis > 0.0 (leptokurtic distribution).
    2. Volatility Clustering: Autocorrelation of absolute returns at lag 1 > 0.05.
    3. Volume-Volatility Correlation: Positive correlation between |returns| and volume (> 0.0).
    """

    def __init__(
        self,
        min_excess_kurtosis: float = 0.0,
        min_vol_clustering_autocorr: float = 0.05,
        min_vol_volume_corr: float = 0.0
    ) -> None:
        self.min_excess_kurtosis = min_excess_kurtosis
        self.min_vol_clustering_autocorr = min_vol_clustering_autocorr
        self.min_vol_volume_corr = min_vol_volume_corr

    def check_path_fidelity(self, df: pd.DataFrame) -> Tuple[bool, Dict[str, float], str]:
        close = df["close"].values
        if len(close) < 30:
            return False, {}, "Insufficient bars for fidelity check"

        rets = np.diff(np.log(close))
        abs_rets = np.abs(rets)
        vol = df["volume"].values[1:]

        # 1. Fat Tails (Excess Kurtosis)
        kurt = float(stats.kurtosis(rets, fisher=True))  # Fisher=True -> 0 for normal

        # 2. Volatility Clustering (Autocorrelation of |returns| at lag 1)
        s_abs = pd.Series(abs_rets)
        autocorr_1 = float(s_abs.autocorr(lag=1))

        # 3. Volume-Volatility Correlation
        s_vol = pd.Series(vol)
        corr_vol_ret = float(s_abs.corr(s_vol)) if s_vol.std() > 1e-9 else 0.0

        metrics = {
            "excess_kurtosis": round(kurt, 4),
            "vol_clustering_autocorr_lag1": round(autocorr_1, 4),
            "vol_volume_correlation": round(corr_vol_ret, 4)
        }

        reasons = []
        if kurt < self.min_excess_kurtosis:
            reasons.append(f"Excess kurtosis ({kurt:.2f}) < {self.min_excess_kurtosis}")
        if autocorr_1 < self.min_vol_clustering_autocorr:
            reasons.append(f"Vol clustering autocorr ({autocorr_1:.2f}) < {self.min_vol_clustering_autocorr}")
        if corr_vol_ret < self.min_vol_volume_corr:
            reasons.append(f"Vol-volume corr ({corr_vol_ret:.2f}) < {self.min_vol_volume_corr}")

        passes = (len(reasons) == 0)
        reason_str = "PASSED" if passes else "; ".join(reasons)
        return passes, metrics, reason_str


# ── Task 6.3: Post-Hoc Policy Robustness Evaluation ────────────────────────────

def evaluate_policy_on_synthetic_paths(
    predict_fn: Callable[[np.ndarray], int],
    normalizer: ObservationNormalizer,
    synthetic_paths: List[pd.DataFrame],
    env_config: Optional[TradingEnvConfig] = None,
    fidelity_gate: Optional[FidelityGate] = None
) -> Dict[str, Any]:
    """
    Evaluates policy step-by-step across all validated synthetic paths,
    measuring distribution of net Sharpe, worst-decile max drawdown, and turnover.
    Never mutates training data.
    """
    cfg = env_config or TradingEnvConfig()
    gate = fidelity_gate or FidelityGate()

    sharpes: List[float] = []
    returns: List[float] = []
    drawdowns: List[float] = []
    turnovers: List[float] = []
    valid_paths_count = 0

    for path_df in synthetic_paths:
        passes, metrics, reason = gate.check_path_fidelity(path_df)
        if not passes:
            log.debug("[SyntheticEval] Path rejected by fidelity gate: %s", reason)
            continue

        valid_paths_count += 1
        env = TradingEnv(path_df, normalizer=normalizer, config=cfg)
        metrics_res = evaluate_policy_on_env(env, predict_fn)

        sharpes.append(metrics_res["annualized_sharpe"])
        returns.append(metrics_res["net_return_pct"])
        drawdowns.append(metrics_res["max_drawdown_pct"])
        turnovers.append(metrics_res["turnover"])

    if not sharpes:
        return {
            "valid_paths_evaluated": 0,
            "median_sharpe": 0.0,
            "worst_decile_drawdown_pct": 0.0,
            "median_net_return_pct": 0.0,
            "turnover_stability_std": 0.0,
            "positive_return_ratio": "0/0"
        }

    positive_count = sum(1 for r in returns if r > 0)
    summary = {
        "valid_paths_evaluated": valid_paths_count,
        "median_sharpe": round(float(np.median(sharpes)), 2),
        "mean_sharpe": round(float(np.mean(sharpes)), 2),
        "std_sharpe": round(float(np.std(sharpes)), 2),
        "worst_decile_drawdown_pct": round(float(np.percentile(drawdowns, 90)), 2),  # 90th percentile of DD is worst decile
        "median_max_drawdown_pct": round(float(np.median(drawdowns)), 2),
        "median_net_return_pct": round(float(np.median(returns)), 2),
        "turnover_mean": round(float(np.mean(turnovers)), 2),
        "turnover_stability_std": round(float(np.std(turnovers)), 2),
        "positive_return_ratio": f"{positive_count}/{valid_paths_count}"
    }

    log.info(
        "[SyntheticEval] Evaluation on %d paths complete: Median Sharpe=%.2f, Worst-Decile DD=%.2f%%, PosRatio=%s",
        valid_paths_count, summary["median_sharpe"], summary["worst_decile_drawdown_pct"], summary["positive_return_ratio"]
    )
    return summary
