"""
tests/test_rl_promotion.py — Tests for Phase 5 RL Governance & Staged Promotion
"""

import os
import json
import pytest
from middleware.strategy_promotion import (
    StrategyPromotionManager,
    PromotionStage,
    RLShadowSoakResult,
    compute_file_sha256
)


@pytest.fixture
def mock_rl_model_files(tmp_path):
    model_path = str(tmp_path / "model.onnx")
    meta_path = str(tmp_path / "model_meta.json")

    # Create dummy binary file
    with open(model_path, "wb") as f:
        f.write(b"fake_onnx_model_bytes_12345")

    meta_data = {
        "feature_schema_hash": "8482438992abcdef",
        "training_config_hash": "9999ffffaaaa1111",
        "symbol": "BTC-USD",
        "normalization_stats": {}
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta_data, f)

    return model_path, meta_path


def test_rl_candidate_registration_and_stage(mock_rl_model_files):
    model_path, meta_path = mock_rl_model_files
    mgr = StrategyPromotionManager()
    strat_id = "rl_btc_candidate"

    # Register RL Candidate
    rec = mgr.register_rl_candidate(
        strategy_id=strat_id,
        name="RL BTC Candidate",
        asset_class="crypto",
        onnx_model_path=model_path,
        meta_path=meta_path,
        params={"min_holding_bars": 3}
    )

    # Invariant: Starts at RESEARCH stage
    assert rec["stage"] == PromotionStage.RESEARCH.value
    assert rec["type"] == "RL_ONNX_POLICY"
    assert rec["weights_sha256"] == compute_file_sha256(model_path)
    assert rec["feature_schema_hash"] == "8482438992abcdef"
    assert mgr.is_authorized_for_live(strat_id) is False


def test_rl_shadow_soak_evaluation(mock_rl_model_files):
    model_path, meta_path = mock_rl_model_files
    mgr = StrategyPromotionManager()
    strat_id = "rl_btc_soak"

    mgr.register_rl_candidate(strat_id, "RL BTC Soak", "crypto", model_path, meta_path)

    # Failed soak: insufficient trade count and days
    bad_soak = RLShadowSoakResult(
        shadow_trades_count=10,
        shadow_duration_days=2.0,
        shadow_max_drawdown_pct=0.03
    )
    ok, reason = mgr.submit_rl_shadow_evaluation(strat_id, bad_soak)
    assert ok is False
    assert "Insufficient shadow soak" in reason
    assert mgr.get_strategy_record(strat_id)["stage"] == PromotionStage.RESEARCH.value

    # Failed soak: high drawdown
    bad_dd = RLShadowSoakResult(
        shadow_trades_count=40,
        shadow_duration_days=10.0,
        shadow_max_drawdown_pct=0.15 # > 8% threshold
    )
    ok, reason = mgr.submit_rl_shadow_evaluation(strat_id, bad_dd)
    assert ok is False
    assert "Shadow soak drawdown" in reason

    # Passing soak
    good_soak = RLShadowSoakResult(
        shadow_trades_count=35,
        shadow_duration_days=8.0,
        shadow_max_drawdown_pct=0.04,
        shadow_sharpe=1.5
    )
    ok, reason = mgr.submit_rl_shadow_evaluation(strat_id, good_soak)
    assert ok is True
    assert mgr.get_strategy_record(strat_id)["stage"] == PromotionStage.PAPER_SOAK.value


def test_rl_paper_sleeve_approval(mock_rl_model_files):
    model_path, meta_path = mock_rl_model_files
    mgr = StrategyPromotionManager()
    strat_id = "rl_btc_approve"

    mgr.register_rl_candidate(strat_id, "RL BTC Approve", "crypto", model_path, meta_path)
    good_soak = RLShadowSoakResult(shadow_trades_count=40, shadow_duration_days=10.0, shadow_max_drawdown_pct=0.03)
    mgr.submit_rl_shadow_evaluation(strat_id, good_soak)

    # Approve for Paper Sleeve
    ok, msg = mgr.approve_rl_for_paper_sleeve(
        strategy_id=strat_id,
        approver_name="Quant Director",
        approver_role="Head of Risk",
        reason="Passed all shadow soak criteria"
    )
    assert ok is True
    rec = mgr.get_strategy_record(strat_id)
    assert rec["paper_sleeve_approval"]["approver_name"] == "Quant Director"


def test_rl_weight_tampering_detection(mock_rl_model_files):
    model_path, meta_path = mock_rl_model_files
    mgr = StrategyPromotionManager()
    strat_id = "rl_btc_tamper"

    mgr.register_rl_candidate(strat_id, "RL BTC Tamper", "crypto", model_path, meta_path)

    # Tamper with the model file on disk
    with open(model_path, "wb") as f:
        f.write(b"tampered_weights_binary_injection")

    good_soak = RLShadowSoakResult(shadow_trades_count=50, shadow_duration_days=10.0, shadow_max_drawdown_pct=0.02)
    ok, reason = mgr.submit_rl_shadow_evaluation(strat_id, good_soak)

    # System detects weight hash mismatch and rejects evaluation
    assert ok is False
    assert "tampered" in reason.lower() or "changed" in reason.lower()
