"""
tests/test_strategy_promotion.py — Tests for Anti-Overfitting Staged Promotion & Governance
"""

import pytest
from middleware.strategy_promotion import (
    StrategyPromotionManager,
    PromotionStage,
    WalkForwardResult,
    PaperSoakResult,
    compute_params_hash
)


def test_full_promotion_lifecycle():
    mgr = StrategyPromotionManager()
    strat_id = "optuna_candidate_01"
    params = {"rsi_period": 14, "bb_std": 2.0}

    # 1. Candidate registered in RESEARCH
    rec = mgr.register_candidate(strat_id, "Bollinger Optuna", "crypto", params)
    assert rec["stage"] == PromotionStage.RESEARCH.value
    assert mgr.is_authorized_for_live(strat_id) is False

    # 2. Walk-forward validation: Fails if overfitted (low WFE)
    bad_wf = WalkForwardResult(in_sample_sharpe=2.5, oos_sharpe=0.8) # WFE = 0.32 < 0.60
    ok, reason = mgr.submit_walk_forward_evaluation(strat_id, bad_wf)
    assert ok is False
    assert "Walk-forward efficiency" in reason
    assert mgr.get_strategy_record(strat_id)["stage"] == PromotionStage.RESEARCH.value

    # Good Walk-Forward: Passes (WFE = 0.80 >= 0.60)
    good_wf = WalkForwardResult(in_sample_sharpe=2.0, oos_sharpe=1.6)
    ok, reason = mgr.submit_walk_forward_evaluation(strat_id, good_wf)
    assert ok is True
    assert mgr.get_strategy_record(strat_id)["stage"] == PromotionStage.WALK_FORWARD.value

    # 3. Paper Soak: Cannot jump to live without soak
    ok, reason = mgr.approve_for_live(strat_id, "Chief Quant", "Risk Lead", "Approved")
    assert ok is False
    assert "Must complete PAPER_SOAK" in reason

    # Submit failed soak (high drawdown)
    bad_soak = PaperSoakResult(paper_trades_count=40, soak_duration_days=10.0, paper_max_drawdown_pct=0.15)
    ok, reason = mgr.submit_paper_soak_evaluation(strat_id, bad_soak)
    assert ok is False
    assert "Paper soak drawdown" in reason

    # Submit passing soak
    good_soak = PaperSoakResult(paper_trades_count=45, soak_duration_days=14.0, paper_max_drawdown_pct=0.03)
    ok, reason = mgr.submit_paper_soak_evaluation(strat_id, good_soak)
    assert ok is True
    assert mgr.get_strategy_record(strat_id)["stage"] == PromotionStage.PAPER_SOAK.value

    # 4. Human Approval for LIVE
    ok, reason = mgr.approve_for_live(strat_id, "Alice Quant", "Head of Trading", "Passed all validation gates")
    assert ok is True
    assert mgr.get_strategy_record(strat_id)["stage"] == PromotionStage.APPROVED_LIVE.value
    assert mgr.is_authorized_for_live(strat_id) is True


def test_parameter_mutation_demotes_to_research():
    mgr = StrategyPromotionManager()
    strat_id = "strat_locked_01"
    params = {"fast_ma": 10, "slow_ma": 50}

    # Register, validate, soak, and promote
    mgr.register_candidate(strat_id, "MA Crossover", "crypto", params)
    mgr.submit_walk_forward_evaluation(strat_id, WalkForwardResult(in_sample_sharpe=2.0, oos_sharpe=1.8))
    mgr.submit_paper_soak_evaluation(strat_id, PaperSoakResult(paper_trades_count=50, soak_duration_days=10.0, paper_max_drawdown_pct=0.02))
    mgr.approve_for_live(strat_id, "Risk Officer", "Manager", "Signed off")

    assert mgr.is_authorized_for_live(strat_id) is True

    # Sneakily attempt to modify parameters (e.g. Optuna hot-reload into prod)
    ok, msg = mgr.update_params(strat_id, {"fast_ma": 5, "slow_ma": 30})
    assert ok is True

    # System immediately strips live authorization and resets to RESEARCH!
    assert mgr.is_authorized_for_live(strat_id) is False
    assert mgr.get_strategy_record(strat_id)["stage"] == PromotionStage.RESEARCH.value
    assert mgr.get_strategy_record(strat_id)["version"] == 2
