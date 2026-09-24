"""
tests/test_strategy_db.py — Tests for strategy persistence and hot-reloading in db_manager
"""

import pytest
from middleware.db_manager import mongo_db


def test_strategy_persistence_and_retrieval():
    strat_data = {
        "strategy_id": "test_strat_01",
        "name": "Test Strategy",
        "asset_class": "crypto",
        "status": "active",
        "parameters": {
            "rsi_len": 14,
            "atr_mult": 2.0
        }
    }

    # 1. Save
    assert mongo_db.save_strategy(strat_data) is True

    # 2. Get
    retrieved = mongo_db.get_strategy("test_strat_01")
    assert retrieved is not None
    assert retrieved["name"] == "Test Strategy"
    assert retrieved["asset_class"] == "crypto"
    assert retrieved["parameters"]["rsi_len"] == 14

    # 3. List
    all_strats = mongo_db.list_strategies()
    assert any(s["strategy_id"] == "test_strat_01" for s in all_strats)

    crypto_strats = mongo_db.list_strategies(asset_class="crypto")
    assert any(s["strategy_id"] == "test_strat_01" for s in crypto_strats)

    stock_strats = mongo_db.list_strategies(asset_class="stock")
    assert not any(s["strategy_id"] == "test_strat_01" for s in stock_strats)

    # 4. Hot-reload parameters
    update_success = mongo_db.update_strategy_params("test_strat_01", {"rsi_len": 21, "stop_pct": 0.03})
    assert update_success is True

    updated = mongo_db.get_strategy("test_strat_01")
    assert updated["parameters"]["rsi_len"] == 21
    assert updated["parameters"]["stop_pct"] == 0.03
    assert updated["parameters"]["atr_mult"] == 2.0  # preserved previous param
