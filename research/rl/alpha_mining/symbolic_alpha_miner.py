"""
research/rl/alpha_mining/symbolic_alpha_miner.py — Cost-Aware Symbolic Alpha Discovery

Tasks 2.1 - 2.4:
1. Operator-constrained symbolic search via gplearn with streaming-safe O(1) operators.
2. Cost-aware fitness scoring net of execution/cost_model.py on TradingEnv.
3. Persistent trial logging to trial_registry.jsonl (source="alpha_mining").
4. Orthogonality filter rejecting candidates with |correlation| > 0.7 against QuantStrategyBridge signals.
"""

from __future__ import annotations
import os
import math
import hashlib
import logging
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd
from gplearn.genetic import SymbolicTransformer
from gplearn.functions import make_function
from gplearn.fitness import make_fitness

from research.rl.trading_env import (
    TradingEnv,
    TradingEnvConfig,
    ObservationNormalizer,
    prepare_market_features
)
from research.rl.train_rl import evaluate_policy_on_env
from research.rl.quant_strategy_bridge import QuantStrategyBridge
from research.rl.trial_registry import trial_registry
from execution.cost_model import CostModelConfig

log = logging.getLogger(__name__)


# ── Task 2.1: Incrementally Computable O(1) Operators ─────────────────────────

def _rolling_delta(x: np.ndarray) -> np.ndarray:
    """O(1) incremental 1-bar delta: x_t - x_{t-1}"""
    res = np.zeros_like(x)
    if len(x) > 1:
        res[1:] = x[1:] - x[:-1]
    return res


def _rolling_ema(x: np.ndarray) -> np.ndarray:
    """O(1) exponential moving average (alpha=0.1)"""
    res = np.zeros_like(x)
    if len(x) == 0:
        return res
    alpha = 0.1
    res[0] = x[0]
    for i in range(1, len(x)):
        res[i] = alpha * x[i] + (1.0 - alpha) * res[i - 1]
    return res


def _rolling_zscore_20(x: np.ndarray) -> np.ndarray:
    """O(1) rolling 20-bar z-score via Welford/moving window, clipped [-5, 5]"""
    s = pd.Series(x)
    mean = s.rolling(20, min_periods=1).mean()
    std = s.rolling(20, min_periods=1).std().replace(0.0, 1.0).fillna(1.0)
    z = (s - mean) / std
    return np.clip(z.values, -5.0, 5.0)


fn_delta = make_function(function=_rolling_delta, name="ts_delta", arity=1)
fn_ema = make_function(function=_rolling_ema, name="ts_ema", arity=1)
fn_zscore = make_function(function=_rolling_zscore_20, name="ts_zscore", arity=1)

STREAMING_FUNCTION_SET = ["add", "sub", "mul", "div", "abs", "neg", fn_delta, fn_ema, fn_zscore]


# ── Task 2.4: Orthogonality Filter ────────────────────────────────────────────

def check_orthogonality(
    candidate_signal: pd.Series,
    bridge_signals: Dict[str, pd.Series],
    correlation_threshold: float = 0.70
) -> Tuple[bool, Dict[str, float]]:
    """
    Computes Pearson correlation against all 4 QuantStrategyBridge signals
    and the mean-aggregated baseline. Rejects candidates with max |correlation| > threshold.
    """
    corrs = {}
    cand = candidate_signal.fillna(0.0)

    # 1. Correlate with each bridge signal
    for name, sig in bridge_signals.items():
        s = sig.fillna(0.0)
        c = float(cand.corr(s)) if cand.std() > 1e-9 and s.std() > 1e-9 else 0.0
        corrs[name] = round(c, 4)

    # 2. Correlate with mean baseline signal
    mean_sig = pd.concat(list(bridge_signals.values()), axis=1).mean(axis=1)
    mean_corr = float(cand.corr(mean_sig)) if cand.std() > 1e-9 and mean_sig.std() > 1e-9 else 0.0
    corrs["baseline_mean"] = round(mean_corr, 4)

    max_corr = max(abs(v) for v in corrs.values())
    is_orthogonal = bool(max_corr <= correlation_threshold)
    return is_orthogonal, corrs


# ── Task 2.1 & 2.2: Symbolic Alpha Discovery Miner ────────────────────────────

class SymbolicAlphaMiner:
    """
    Discovers new mathematical alpha signals from market features using genetic programming,
    evaluating candidate expressions net of costs on TradingEnv.
    """

    def __init__(
        self,
        population_size: int = 50,
        generations: int = 3,
        tournament_size: int = 10,
        correlation_threshold: float = 0.70,
        random_state: int = 42
    ) -> None:
        self.population_size = population_size
        self.generations = generations
        self.tournament_size = tournament_size
        self.correlation_threshold = correlation_threshold
        self.random_state = random_state

    def mine_alphas(
        self,
        df: pd.DataFrame,
        target_return_horizon: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Runs genetic programming search on prepared features.
        Scores candidate programs net of transaction costs, logs all trials,
        and applies the orthogonality filter.
        """
        feats_df = prepare_market_features(df).reset_index(drop=True)
        # Numerical feature columns only
        feature_cols = [
            c for c in feats_df.columns
            if c not in ["timestamp", "date", "symbol"] and np.issubdtype(feats_df[c].dtype, np.number)
        ]
        X = feats_df[feature_cols].values
        # Forward return target for genetic guiding
        close = feats_df["close"].values
        y_target = np.zeros(len(close))
        if len(close) > target_return_horizon:
            y_target[:-target_return_horizon] = np.log(close[target_return_horizon:] / close[:-target_return_horizon])

        # Precompute bridge signals for orthogonality filtering
        bridge_sigs = QuantStrategyBridge.get_all_quant_signals(df)

        log.info(
            "[SymbolicAlphaMiner] Starting alpha search (pop=%d, gen=%d, features=%d)",
            self.population_size, self.generations, len(feature_cols)
        )

        # ── Setup Cost-Aware Fitness (Task 2.2) ───────────────────────────────
        def cost_aware_sharpe_fitness(y_true, y_pred, sample_weight=None) -> float:
            """
            Scores formula net of transaction costs by simulating policy on TradingEnv.
            """
            raw_sig = np.nan_to_num(y_pred, nan=0.0)
            # Threshold into discrete actions: 0 (Short), 1 (Flat), 2 (Long)
            thresh = np.std(raw_sig) * 0.5 if np.std(raw_sig) > 1e-9 else 0.01
            actions = np.where(raw_sig > thresh, 2, np.where(raw_sig < -thresh, 0, 1))

            # Run through TradingEnv under exact CostModel
            env = TradingEnv(df, config=TradingEnvConfig(min_holding_bars=1))
            res = evaluate_policy_on_env(env, lambda obs: int(actions[min(env.current_step, len(actions) - 1)]))
            ann_sharpe = float(res["annualized_sharpe"])

            # Log trial to persistent trial registry (Task 2.3)
            formula_hash = hashlib.sha256(raw_sig[:50].tobytes()).hexdigest()[:16]
            trial_registry.record_trial(
                config_hash=formula_hash,
                fold="alpha_mining",
                seed=self.random_state,
                sharpe=ann_sharpe,
                source="alpha_mining",
                extra_meta={"net_return_pct": res["net_return_pct"], "trade_count": res["trade_count"]}
            )

            return ann_sharpe

        custom_metric = make_fitness(function=cost_aware_sharpe_fitness, greater_is_better=True)

        gp = SymbolicTransformer(
            generations=self.generations,
            population_size=self.population_size,
            hall_of_fame=min(50, self.population_size),
            tournament_size=min(self.tournament_size, self.population_size),
            function_set=STREAMING_FUNCTION_SET,
            metric=custom_metric,
            const_range=(-1.0, 1.0),
            n_components=min(5, self.population_size),
            random_state=self.random_state,
            verbose=0
        )

        gp.fit(X, y_target)

        accepted_alphas: List[Dict[str, Any]] = []
        for i, program in enumerate(gp):
            formula_str = str(program)
            raw_output = program.execute(X)
            cand_sig = pd.Series(raw_output, index=df.index).fillna(0.0)

            # Evaluate net performance
            thresh = float(cand_sig.std() * 0.5) if cand_sig.std() > 1e-9 else 0.01
            actions = np.where(cand_sig > thresh, 2, np.where(cand_sig < -thresh, 0, 1))
            env = TradingEnv(df, config=TradingEnvConfig(min_holding_bars=1))
            res = evaluate_policy_on_env(env, lambda obs: int(actions[min(env.current_step, len(actions) - 1)]))

            # Orthogonality filter check (Task 2.4)
            is_orthogonal, corrs = check_orthogonality(
                candidate_signal=cand_sig,
                bridge_signals=bridge_sigs,
                correlation_threshold=self.correlation_threshold
            )

            record = {
                "alpha_id": f"mined_alpha_{i+1}",
                "formula": formula_str,
                "net_sharpe": res["annualized_sharpe"],
                "net_return_pct": res["net_return_pct"],
                "trade_count": res["trade_count"],
                "is_orthogonal": is_orthogonal,
                "correlations": corrs
            }

            if is_orthogonal and res["annualized_sharpe"] > 0:
                accepted_alphas.append(record)
                log.info(
                    "[SymbolicAlphaMiner] Candidate %d ACCEPTED (Sharpe: %.2f, NetRet: %.2f%%, Formula: %s)",
                    i + 1, res["annualized_sharpe"], res["net_return_pct"], formula_str
                )
            else:
                log.info(
                    "[SymbolicAlphaMiner] Candidate %d REJECTED (Orthogonal: %s, MaxCorr: %.2f)",
                    i + 1, is_orthogonal, max(abs(v) for v in corrs.values())
                )

        return accepted_alphas
