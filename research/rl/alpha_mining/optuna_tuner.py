"""
research/rl/alpha_mining/optuna_tuner.py — Walk-Forward Stability Parameter Optimization

Task 2.5:
Uses Optuna to tune strategy parameters for QuantStrategyBridge strategies
(Dual Thrust, Awesome Oscillator, RSI Pattern), optimizing for out-of-sample
walk-forward stability across purged folds rather than in-sample curve-fitting.
Every trial is logged to trial_registry.jsonl (source="hparam_sweep").
"""

from __future__ import annotations
import os
import json
import hashlib
import logging
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd
import optuna

from research.rl.trading_env import TradingEnv, TradingEnvConfig
from research.rl.train_rl import create_purged_walk_forward_splits, evaluate_policy_on_env
from research.rl.quant_strategy_bridge import QuantStrategyBridge
from research.rl.trial_registry import trial_registry

log = logging.getLogger(__name__)
optuna.logging.set_verbosity(optuna.logging.WARNING)


class OptunaStrategyTuner:
    """
    Optuna parameter optimizer maximizing walk-forward stability (penalizing fold variance)
    across purged validation splits.
    """

    def __init__(
        self,
        strategy_name: str = "dual_thrust",
        n_trials: int = 20,
        n_folds: int = 3,
        embargo_bars: int = 20
    ) -> None:
        self.strategy_name = strategy_name
        self.n_trials = n_trials
        self.n_folds = n_folds
        self.embargo_bars = embargo_bars

    def tune(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Runs walk-forward stability tuning.
        Logs every trial to trial_registry.
        """
        splits = create_purged_walk_forward_splits(df, n_folds=self.n_folds, embargo_bars=self.embargo_bars)
        if not splits:
            raise ValueError("Insufficient data to generate walk-forward splits.")

        def objective(trial: optuna.Trial) -> float:
            if self.strategy_name == "dual_thrust":
                params = {
                    "k1": trial.suggest_float("k1", 0.1, 1.0, step=0.05),
                    "k2": trial.suggest_float("k2", 0.1, 1.0, step=0.05),
                    "lookback_bars": trial.suggest_int("lookback_bars", 5, 40)
                }
                sig_fn = lambda d: QuantStrategyBridge.dual_thrust_signals(d, **params)

            elif self.strategy_name == "awesome_oscillator":
                fast = trial.suggest_int("fast_period", 3, 15)
                slow = trial.suggest_int("slow_period", 20, 50)
                params = {"fast_period": fast, "slow_period": slow}
                sig_fn = lambda d: QuantStrategyBridge.awesome_oscillator_signals(d, **params)

            elif self.strategy_name == "rsi_pattern":
                params = {
                    "period": trial.suggest_int("period", 7, 25),
                    "oversold": trial.suggest_float("oversold", 20.0, 40.0, step=2.0),
                    "overbought": trial.suggest_float("overbought", 60.0, 80.0, step=2.0)
                }
                sig_fn = lambda d: QuantStrategyBridge.rsi_pattern_signals(d, **params)

            else:
                raise ValueError(f"Unknown strategy: {self.strategy_name}")

            # Compute config hash
            param_hash = hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()[:16]

            # Evaluate on each validation fold
            fold_sharpes: List[float] = []
            for split in splits:
                env = TradingEnv(split.val_df, config=TradingEnvConfig(min_holding_bars=1))
                sigs = sig_fn(split.val_df)

                def policy(obs: np.ndarray) -> int:
                    idx = min(env.current_step, len(sigs) - 1)
                    sig = sigs.iloc[idx]
                    return 2 if sig > 0 else (0 if sig < 0 else 1)

                eval_res = evaluate_policy_on_env(env, policy)
                s = eval_res["annualized_sharpe"]
                fold_sharpes.append(s)

                # Log each fold trial to trial registry (Task 1.2 / 2.5)
                trial_registry.record_trial(
                    config_hash=param_hash,
                    fold=split.fold_idx,
                    seed=trial.number,
                    sharpe=s,
                    source="hparam_sweep",
                    extra_meta={"strategy": self.strategy_name, "params": params, "net_return_pct": eval_res["net_return_pct"]}
                )

            mean_sr = float(np.mean(fold_sharpes))
            std_sr = float(np.std(fold_sharpes))

            # Stability objective: Maximize mean Sharpe minus dispersion penalty
            stability_score = mean_sr - (1.0 * std_sr)
            return stability_score

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=self.n_trials)

        best = {
            "strategy": self.strategy_name,
            "best_params": study.best_params,
            "best_stability_score": round(study.best_value, 4),
            "total_trials": len(study.trials)
        }
        log.info("[OptunaStrategyTuner] Tuning complete for %s: Best Score=%.4f, Params=%s",
                 self.strategy_name, study.best_value, study.best_params)
        return best
