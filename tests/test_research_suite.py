"""
tests/test_research_suite.py — Unit tests for the isolated research & tuning suite
"""

import pytest
import pandas as pd
import numpy as np
from research.vbt_screener import FastVectorizedScreener
from research.bt_validator import BacktestValidator
from research.optuna_tuner import StrategyOptunaTuner
from strategies.crypto.binh_cluc import BinhClucStrategy
from data_pipeline.feature_standardizer import compute_standard_features
from middleware.db_manager import mongo_db


def _make_historical_candles(n=80):
    np.random.seed(42)
    prices = 100.0 + np.cumsum(np.random.randn(n) * 1.5)
    df = pd.DataFrame({
        "open": prices * 0.999,
        "high": prices * 1.008,
        "low": prices * 0.992,
        "close": prices,
        "volume": np.random.uniform(500, 2500, n)
    })
    return compute_standard_features(df)


def test_vectorized_screener():
    screener = FastVectorizedScreener()
    df = _make_historical_candles()

    results = screener.screen_rsi_strategy(
        df,
        rsi_buy_range=[30.0, 35.0],
        rsi_sell_range=[65.0, 70.0]
    )

    assert len(results) > 0
    top = results[0]
    assert "sharpe_ratio" in top
    assert "total_return_pct" in top
    assert "max_drawdown_pct" in top
    # Results must be sorted descending by Sharpe
    if len(results) > 1:
        assert results[0]["sharpe_ratio"] >= results[1]["sharpe_ratio"]


def test_backtest_validator():
    validator = BacktestValidator()
    df = _make_historical_candles()
    strat = BinhClucStrategy()

    metrics = validator.validate_strategy(strat, "BTC-USD", df)
    assert "total_return_pct" in metrics
    assert "sharpe_ratio" in metrics
    assert "max_drawdown_pct" in metrics
    assert metrics["strategy_id"] == "crypto_binh_cluc_01"


def test_optuna_tuner_and_db_sync():
    df = _make_historical_candles()
    strat_id = "test_optuna_strat_01"

    # Pre-register strategy in DB
    mongo_db.save_strategy({
        "strategy_id": strat_id,
        "name": "Optuna Test Strategy",
        "asset_class": "crypto",
        "parameters": {"rsi_buy_threshold": 30.0}
    })

    tuner = StrategyOptunaTuner(
        strategy_factory=lambda params: BinhClucStrategy(strategy_id=strat_id, params=params),
        symbol="BTC-USD",
        df=df,
        study_name="test_quick_study"
    )

    res = tuner.optimize_binh_cluc(n_trials=5)
    assert "best_params" in res
    assert "best_sharpe" in res
    assert len(res["best_params"]) > 0

    # Test sync to DB
    sync_ok = tuner.sync_to_db(strat_id, res["best_params"])
    assert sync_ok is True

    # Verify updated params in DB
    updated = mongo_db.get_strategy(strat_id)
    assert updated["parameters"]["rsi_buy_threshold"] == res["best_params"]["rsi_buy_threshold"]
