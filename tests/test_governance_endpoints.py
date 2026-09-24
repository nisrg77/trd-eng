"""
tests/test_governance_endpoints.py — Tests for Strategy Governance & Risk REST Endpoints
"""

import pytest
from fastapi import HTTPException
from services.ws_server import (
    list_strategies,
    get_strategy_details,
    toggle_strategy_status,
    promote_strategy_to_live,
    get_risk_status,
    trigger_kill_switch,
    reset_kill_switch
)
from goals.hardened_risk_guard import hardened_risk_guard
from middleware.strategy_promotion import promotion_manager, PromotionStage, WalkForwardResult, PaperSoakResult
from middleware.db_manager import mongo_db


def test_risk_status_and_kill_switch_endpoints():
    # 1. Reset kill switch
    res_reset = reset_kill_switch(admin_key="admin_test")
    assert res_reset["status"] == "ARMED"
    assert hardened_risk_guard.is_kill_switch_active is False

    # 2. Check risk status
    status = get_risk_status()
    assert status["kill_switch_active"] is False
    assert status["max_monthly_loss_usd"] == -1000.0
    assert status["max_position_size_usd"] == 5000.0

    # 3. Trigger emergency kill switch
    res_halt = trigger_kill_switch(
        payload={"reason": "Testing manual kill switch"},
        admin_key="admin_test"
    )
    assert res_halt["status"] == "HALTED"
    assert hardened_risk_guard.is_kill_switch_active is True

    # 4. Clean up
    reset_kill_switch(admin_key="admin_test")
    assert hardened_risk_guard.is_kill_switch_active is False


def test_strategy_promotion_and_live_toggle_gate():
    strat_id = "governance_strat_01"
    params = {"rsi_len": 14, "std_dev": 2.0}

    # Save to db_manager and register with promotion_manager
    mongo_db.save_strategy({
        "strategy_id": strat_id,
        "name": "Governance Test Strat",
        "asset_class": "crypto",
        "status": "inactive",
        "parameters": params
    })
    promotion_manager.register_candidate(strat_id, "Governance Test Strat", "crypto", params)

    # 1. Attempting to activate for LIVE while in RESEARCH stage must fail with 403 Forbidden
    with pytest.raises(HTTPException) as exc_info:
        toggle_strategy_status(
            strategy_id=strat_id,
            payload={"status": "active", "mode": "live"},
            admin_key="admin_test"
        )
    assert exc_info.value.status_code == 403
    assert "not authorized for LIVE trading" in exc_info.value.detail

    # 2. Advance through promotion stages
    promotion_manager.submit_walk_forward_evaluation(
        strat_id,
        WalkForwardResult(in_sample_sharpe=2.0, oos_sharpe=1.6)
    )
    promotion_manager.submit_paper_soak_evaluation(
        strat_id,
        PaperSoakResult(paper_trades_count=40, soak_duration_days=10.0, paper_max_drawdown_pct=0.03)
    )

    # 3. Promote via endpoint
    promote_res = promote_strategy_to_live(
        strategy_id=strat_id,
        payload={"approver_name": "Bob RiskLead", "approver_role": "Chief Risk Officer", "reason": "Full soak passed"},
        admin_key="admin_test"
    )
    assert promote_res["status"] == "success"
    assert promotion_manager.is_authorized_for_live(strat_id) is True

    # 4. Now activating for LIVE succeeds!
    toggle_res = toggle_strategy_status(
        strategy_id=strat_id,
        payload={"status": "active", "mode": "live"},
        admin_key="admin_test"
    )
    assert toggle_res["status"] == "success"
    assert toggle_res["new_status"] == "active"

    # 5. Verify details endpoint
    details = get_strategy_details(strat_id)
    assert details["strategy"]["strategy_id"] == strat_id
    assert details["authorized_for_live"] is True
