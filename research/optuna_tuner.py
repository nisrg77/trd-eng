"""
research/optuna_tuner.py — Automated Bayesian Hyperparameter Optimizer

Uses Optuna's Tree-structured Parzen Estimator (TPE) sampler to search strategy parameter spaces,
prune underperforming configurations early, and push winning parameters directly to MongoDB Atlas.
"""

from __future__ import annotations
import os
import logging
from typing import Dict, Any, Optional
import optuna
import pandas as pd
from strategies.base_strategy import BaseStrategy
from research.bt_validator import BacktestValidator
from middleware.db_manager import mongo_db

log = logging.getLogger(__name__)
optuna.logging.set_verbosity(optuna.logging.WARNING)


class StrategyOptunaTuner:
    """
    Automated hyperparameter tuner powered by Optuna.
    """

    def __init__(
        self,
        strategy_factory,
        symbol: str,
        df: pd.DataFrame,
        study_name: Optional[str] = None,
        db_path: Optional[str] = None
    ) -> None:
        self.strategy_factory = strategy_factory
        self.symbol = symbol
        self.df = df
        self.study_name = study_name or f"study_{symbol.replace('-', '_')}"
        self.storage = f"sqlite:///{db_path}" if db_path else None
        self.validator = BacktestValidator()

    def optimize_binh_cluc(self, n_trials: int = 30) -> Dict[str, Any]:
        """Optimizes BinhCluc dip-buying parameters."""
        def objective(trial: optuna.Trial) -> float:
            rsi_buy = trial.suggest_float("rsi_buy_threshold", 20.0, 38.0)
            vol_mult = trial.suggest_float("volume_mult", 1.1, 2.2)
            stop_pct = trial.suggest_float("stop_loss_pct", 0.02, 0.06)

            strat: BaseStrategy = self.strategy_factory(params={
                "rsi_buy_threshold": rsi_buy,
                "volume_mult": vol_mult,
                "stop_loss_pct": stop_pct
            })

            metrics = self.validator.validate_strategy(strat, self.symbol, self.df)
            sharpe = metrics.get("sharpe_ratio", -10.0)
            dd = metrics.get("max_drawdown_pct", 100.0)

            # Early pruning penalty for high drawdown
            if dd > 15.0:
                raise optuna.TrialPruned()

            return float(sharpe)

        study = optuna.create_study(
            study_name=self.study_name,
            storage=self.storage,
            direction="maximize",
            load_if_exists=True
        )
        study.optimize(objective, n_trials=n_trials)

        best_params = study.best_params
        best_sharpe = study.best_value

        log.info(
            "[%s] Optimization complete. Best Sharpe: %s | Best Params: %s",
            self.study_name,
            best_sharpe,
            best_params
        )

        return {
            "best_params": best_params,
            "best_sharpe": best_sharpe,
            "total_trials": len(study.trials)
        }

    def sync_to_db(self, strategy_id: str, best_params: Dict[str, Any]) -> bool:
        """Pushes best parameters directly to MongoDB Atlas collection 'strategies'."""
        return mongo_db.update_strategy_params(strategy_id, best_params)
