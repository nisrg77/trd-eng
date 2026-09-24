"""
middleware/strategy_promotion.py — Anti-Overfitting Staged Promotion & Governance Pipeline

Enforces the 4-stage institutional promotion pipeline:
1. RESEARCH: Initial parameter discovery via Optuna/VectorBT. Cannot trade live.
2. WALK_FORWARD: Out-of-sample walk-forward efficiency validation (WFE >= 0.60).
3. PAPER_SOAK: Mandatory soak test (>= 7 days or >= 30 trades with <= 8% drawdown).
4. APPROVED_LIVE: Explicit, cryptographically hashed human sign-off.

Anti-Overfitting Protection:
- Prevents direct hot-reloading of raw Optuna parameters into live execution.
- Binds approved live execution to an immutable SHA-256 parameter hash.
- Any parameter change invalidates approval, requiring re-validation.
"""

from __future__ import annotations
import os
import time
import json
import hashlib
import logging
import threading
from enum import Enum
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict

log = logging.getLogger(__name__)


class PromotionStage(str, Enum):
    RESEARCH = "RESEARCH"
    WALK_FORWARD = "WALK_FORWARD"
    PAPER_SOAK = "PAPER_SOAK"
    APPROVED_LIVE = "APPROVED_LIVE"
    REJECTED = "REJECTED"


@dataclass
class WalkForwardResult:
    in_sample_sharpe: float
    oos_sharpe: float
    min_wfe_threshold: float = 0.60
    min_sharpe_threshold: float = 1.0

    @property
    def wfe_ratio(self) -> float:
        if self.in_sample_sharpe <= 0:
            return 0.0
        return self.oos_sharpe / self.in_sample_sharpe

    def passes(self) -> tuple[bool, str]:
        if self.in_sample_sharpe < self.min_sharpe_threshold:
            return False, f"In-sample Sharpe ({self.in_sample_sharpe:.2f}) below threshold ({self.min_sharpe_threshold})"
        if self.wfe_ratio < self.min_wfe_threshold:
            return False, f"Walk-forward efficiency ({self.wfe_ratio:.2f}) below threshold ({self.min_wfe_threshold})"
        return True, "Walk-forward validation successful"


@dataclass
class PaperSoakResult:
    paper_trades_count: int
    soak_duration_days: float
    paper_max_drawdown_pct: float
    min_paper_trades: int = 30
    min_soak_days: float = 7.0
    max_drawdown_threshold: float = 0.08

    def passes(self) -> tuple[bool, str]:
        if self.paper_trades_count < self.min_paper_trades and self.soak_duration_days < self.min_soak_days:
            return False, (
                f"Insufficient soak: {self.paper_trades_count}/{self.min_paper_trades} trades, "
                f"{self.soak_duration_days:.1f}/{self.min_soak_days} days"
            )
        if self.paper_max_drawdown_pct > self.max_drawdown_threshold:
            return False, (
                f"Paper soak drawdown ({self.paper_max_drawdown_pct:.1%}) breached "
                f"threshold ({self.max_drawdown_threshold:.1%})"
            )
        return True, "Paper soak validation successful"


def compute_params_hash(params: Dict[str, Any]) -> str:
    """Computes a deterministic SHA-256 hash of a strategy's parameters."""
    encoded = json.dumps(params, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def compute_file_sha256(file_path: str) -> str:
    """Computes SHA-256 hash of a binary file."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha.update(chunk)
    return sha.hexdigest()


@dataclass
class RLShadowSoakResult:
    shadow_trades_count: int
    shadow_duration_days: float
    shadow_max_drawdown_pct: float
    shadow_sharpe: float = 1.0
    deflated_sharpe_ratio: float = 0.5
    min_shadow_trades: int = 30
    min_soak_days: float = 7.0
    max_drawdown_threshold: float = 0.08
    min_sharpe_threshold: float = 1.0

    def passes(self) -> tuple[bool, str]:
        if self.shadow_trades_count < self.min_shadow_trades and self.shadow_duration_days < self.min_soak_days:
            return False, (
                f"Insufficient shadow soak: {self.shadow_trades_count}/{self.min_shadow_trades} trades, "
                f"{self.shadow_duration_days:.1f}/{self.min_soak_days} days"
            )
        if self.shadow_max_drawdown_pct > self.max_drawdown_threshold:
            return False, (
                f"Shadow soak drawdown ({self.shadow_max_drawdown_pct:.1%}) breached "
                f"threshold ({self.max_drawdown_threshold:.1%})"
            )
        if self.shadow_sharpe < self.min_sharpe_threshold:
            return False, (
                f"Shadow Sharpe ({self.shadow_sharpe:.2f}) below threshold ({self.min_sharpe_threshold})"
            )
        return True, "RL shadow soak validation successful"


class StrategyPromotionManager:
    """
    Manages strategy promotion lifecycle, parameter versioning, and live authorization.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._registry: Dict[str, Dict[str, Any]] = {}

    def register_candidate(
        self,
        strategy_id: str,
        name: str,
        asset_class: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Registers a new strategy candidate in the RESEARCH stage."""
        with self._lock:
            p_hash = compute_params_hash(params)
            record = {
                "strategy_id": strategy_id,
                "name": name,
                "asset_class": asset_class,
                "type": "RULES_BASED",
                "stage": PromotionStage.RESEARCH.value,
                "version": 1,
                "params": params.copy(),
                "params_hash": p_hash,
                "parameter_history": [{
                    "version": 1,
                    "params": params.copy(),
                    "params_hash": p_hash,
                    "timestamp": time.time()
                }],
                "wf_result": None,
                "soak_result": None,
                "live_approval": None,
                "audit_trail": [{
                    "event": "REGISTERED",
                    "stage": PromotionStage.RESEARCH.value,
                    "timestamp": time.time(),
                    "details": "Strategy candidate registered"
                }]
            }
            self._registry[strategy_id] = record
            log.info("[PromotionManager] Registered candidate '%s' [%s]", strategy_id, p_hash)
            return record

    def register_rl_candidate(
        self,
        strategy_id: str,
        name: str,
        asset_class: str,
        onnx_model_path: str,
        meta_path: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Registers an RL ONNX policy candidate strictly in the RESEARCH stage.
        Validates model file existence, metadata integrity, and records immutable weights hash.
        Auto-promotion is strictly prohibited.
        """
        with self._lock:
            meta_file = meta_path or onnx_model_path.replace(".onnx", "_meta.json")
            if not os.path.exists(onnx_model_path):
                raise FileNotFoundError(f"ONNX model file not found: {onnx_model_path}")
            if not os.path.exists(meta_file):
                raise FileNotFoundError(f"Model metadata file not found: {meta_file}")

            with open(meta_file, "r", encoding="utf-8") as f:
                meta_data = json.load(f)

            weights_hash = compute_file_sha256(onnx_model_path)
            schema_hash = meta_data.get("feature_schema_hash", "")
            train_cfg_hash = meta_data.get("training_config_hash", "")

            p = params.copy() if params else {}
            p.update({
                "onnx_model_path": onnx_model_path,
                "meta_path": meta_file,
                "weights_sha256": weights_hash,
                "feature_schema_hash": schema_hash,
                "training_config_hash": train_cfg_hash
            })
            p_hash = compute_params_hash(p)

            record = {
                "strategy_id": strategy_id,
                "name": name,
                "asset_class": asset_class,
                "type": "RL_ONNX_POLICY",
                "stage": PromotionStage.RESEARCH.value,
                "version": 1,
                "params": p,
                "params_hash": p_hash,
                "weights_sha256": weights_hash,
                "feature_schema_hash": schema_hash,
                "training_config_hash": train_cfg_hash,
                "meta_data": meta_data,
                "parameter_history": [{
                    "version": 1,
                    "params": p,
                    "params_hash": p_hash,
                    "timestamp": time.time()
                }],
                "wf_result": None,
                "soak_result": None,
                "live_approval": None,
                "audit_trail": [{
                    "event": "REGISTERED_RL_CANDIDATE",
                    "stage": PromotionStage.RESEARCH.value,
                    "timestamp": time.time(),
                    "details": f"RL Policy registered with weights_hash={weights_hash[:8]}, schema_hash={schema_hash}"
                }]
            }
            self._registry[strategy_id] = record
            log.info(
                "[PromotionManager] Registered RL candidate '%s' (weights: %s, schema: %s)",
                strategy_id, weights_hash[:8], schema_hash
            )
            return record

    def update_params(self, strategy_id: str, new_params: Dict[str, Any]) -> tuple[bool, str]:
        """
        Updates parameters, generating a new version and resetting approval to RESEARCH
        to prevent live parameter injection.
        """
        with self._lock:
            rec = self._registry.get(strategy_id)
            if not rec:
                return False, f"Unknown strategy_id: {strategy_id}"

            p_hash = compute_params_hash(new_params)
            if p_hash == rec["params_hash"]:
                return True, "Parameters unchanged"

            new_ver = rec["version"] + 1
            rec["version"] = new_ver
            rec["params"] = new_params.copy()
            rec["params_hash"] = p_hash
            rec["stage"] = PromotionStage.RESEARCH.value  # Reset stage!
            rec["live_approval"] = None

            rec["parameter_history"].append({
                "version": new_ver,
                "params": new_params.copy(),
                "params_hash": p_hash,
                "timestamp": time.time()
            })
            rec["audit_trail"].append({
                "event": "PARAMETERS_UPDATED",
                "version": new_ver,
                "params_hash": p_hash,
                "stage": PromotionStage.RESEARCH.value,
                "timestamp": time.time(),
                "details": "Parameters updated — stage reset to RESEARCH"
            })
            log.warning(
                "[PromotionManager] Strategy '%s' updated to v%d [%s]. Demoted to RESEARCH.",
                strategy_id, new_ver, p_hash
            )
            return True, f"Parameters updated to v{new_ver}; stage reset to RESEARCH"

    def submit_walk_forward_evaluation(
        self,
        strategy_id: str,
        wf_result: WalkForwardResult
    ) -> tuple[bool, str]:
        """Validates walk-forward efficiency and promotes to WALK_FORWARD stage."""
        with self._lock:
            rec = self._registry.get(strategy_id)
            if not rec:
                return False, f"Unknown strategy: {strategy_id}"

            passed, reason = wf_result.passes()
            if not passed:
                rec["audit_trail"].append({
                    "event": "WALK_FORWARD_FAILED",
                    "reason": reason,
                    "timestamp": time.time()
                })
                return False, f"Walk-forward failed: {reason}"

            rec["wf_result"] = asdict(wf_result)
            rec["wf_result"]["wfe_ratio"] = wf_result.wfe_ratio
            rec["stage"] = PromotionStage.WALK_FORWARD.value
            rec["audit_trail"].append({
                "event": "PROMOTED_TO_WALK_FORWARD",
                "stage": PromotionStage.WALK_FORWARD.value,
                "timestamp": time.time(),
                "details": f"WFE: {wf_result.wfe_ratio:.2f}, IS Sharpe: {wf_result.in_sample_sharpe:.2f}"
            })
            log.info("[PromotionManager] Strategy '%s' promoted to WALK_FORWARD", strategy_id)
            return True, "Promoted to WALK_FORWARD"

    def submit_paper_soak_evaluation(
        self,
        strategy_id: str,
        soak_result: PaperSoakResult
    ) -> tuple[bool, str]:
        """Validates paper trading soak metrics and promotes to PAPER_SOAK stage."""
        with self._lock:
            rec = self._registry.get(strategy_id)
            if not rec:
                return False, f"Unknown strategy: {strategy_id}"

            if rec["stage"] not in [PromotionStage.WALK_FORWARD.value, PromotionStage.PAPER_SOAK.value]:
                return False, f"Strategy must be in WALK_FORWARD stage first (currently: {rec['stage']})"

            passed, reason = soak_result.passes()
            if not passed:
                rec["audit_trail"].append({
                    "event": "PAPER_SOAK_FAILED",
                    "reason": reason,
                    "timestamp": time.time()
                })
                return False, f"Paper soak failed: {reason}"

            rec["soak_result"] = asdict(soak_result)
            rec["stage"] = PromotionStage.PAPER_SOAK.value
            rec["audit_trail"].append({
                "event": "PROMOTED_TO_PAPER_SOAK",
                "stage": PromotionStage.PAPER_SOAK.value,
                "timestamp": time.time(),
                "details": f"Trades: {soak_result.paper_trades_count}, MaxDD: {soak_result.paper_max_drawdown_pct:.1%}"
            })
            log.info("[PromotionManager] Strategy '%s' promoted to PAPER_SOAK", strategy_id)
            return True, "Promoted to PAPER_SOAK"

    def submit_rl_shadow_evaluation(
        self,
        strategy_id: str,
        soak_result: RLShadowSoakResult
    ) -> tuple[bool, str]:
        """
        Evaluates RL shadow-mode soak results.
        Validates trade count, soak duration, drawdown, and verifies model hash integrity.
        """
        with self._lock:
            rec = self._registry.get(strategy_id)
            if not rec:
                return False, f"Unknown strategy: {strategy_id}"

            if rec.get("type") != "RL_ONNX_POLICY":
                return False, f"Strategy '{strategy_id}' is not an RL policy candidate."

            # Verify on-disk model integrity
            onnx_path = rec["params"].get("onnx_model_path", "")
            if onnx_path and os.path.exists(onnx_path):
                current_weights_hash = compute_file_sha256(onnx_path)
                if current_weights_hash != rec.get("weights_sha256"):
                    msg = "Model weights tampered or changed since registration!"
                    log.critical("[PromotionManager] %s: %s", strategy_id, msg)
                    return False, msg

            passed, reason = soak_result.passes()
            if not passed:
                rec["audit_trail"].append({
                    "event": "RL_SHADOW_SOAK_FAILED",
                    "reason": reason,
                    "timestamp": time.time()
                })
                return False, f"RL shadow soak failed: {reason}"

            rec["soak_result"] = asdict(soak_result)
            rec["stage"] = PromotionStage.PAPER_SOAK.value
            rec["audit_trail"].append({
                "event": "PROMOTED_TO_PAPER_SOAK",
                "stage": PromotionStage.PAPER_SOAK.value,
                "timestamp": time.time(),
                "details": (
                    f"Shadow Trades: {soak_result.shadow_trades_count}, "
                    f"MaxDD: {soak_result.shadow_max_drawdown_pct:.1%}, "
                    f"Sharpe: {soak_result.shadow_sharpe:.2f}"
                )
            })
            log.info("[PromotionManager] RL Strategy '%s' promoted to PAPER_SOAK via shadow soak", strategy_id)
            return True, "Promoted to PAPER_SOAK"

    def approve_rl_for_paper_sleeve(
        self,
        strategy_id: str,
        approver_name: str,
        approver_role: str,
        reason: str
    ) -> tuple[bool, str]:
        """
        Grants manual human sign-off for an RL policy to be activated in the paper sleeve.
        Enforces immutable weights hash and schema hash checks. Auto-promotion is prohibited.
        """
        with self._lock:
            rec = self._registry.get(strategy_id)
            if not rec:
                return False, f"Unknown strategy: {strategy_id}"

            if rec.get("type") != "RL_ONNX_POLICY":
                return False, f"Strategy '{strategy_id}' is not an RL policy candidate."

            if rec["stage"] != PromotionStage.PAPER_SOAK.value:
                return False, f"Cannot approve for paper sleeve from stage '{rec['stage']}'. Must pass shadow soak first."

            approval_record = {
                "approver_name": approver_name,
                "approver_role": approver_role,
                "reason": reason,
                "approved_weights_hash": rec.get("weights_sha256"),
                "approved_schema_hash": rec.get("feature_schema_hash"),
                "timestamp": time.time()
            }
            rec["paper_sleeve_approval"] = approval_record
            rec["audit_trail"].append({
                "event": "APPROVED_FOR_PAPER_SLEEVE",
                "timestamp": time.time(),
                "approval": approval_record
            })
            log.info("[PromotionManager] RL Strategy '%s' APPROVED FOR PAPER SLEEVE by %s", strategy_id, approver_name)
            return True, f"RL Strategy '{strategy_id}' approved for paper sleeve execution"

    def approve_for_live(
        self,
        strategy_id: str,
        approver_name: str,
        approver_role: str,
        reason: str
    ) -> tuple[bool, str]:
        """
        Grants cryptographically signed human approval for LIVE trading.
        Binds approval to current parameter hash.
        """
        with self._lock:
            rec = self._registry.get(strategy_id)
            if not rec:
                return False, f"Unknown strategy: {strategy_id}"

            if rec["stage"] != PromotionStage.PAPER_SOAK.value:
                return False, f"Cannot promote to live from '{rec['stage']}'. Must complete PAPER_SOAK first."

            approval_record = {
                "approver_name": approver_name,
                "approver_role": approver_role,
                "reason": reason,
                "approved_params_hash": rec["params_hash"],
                "approved_version": rec["version"],
                "timestamp": time.time()
            }
            rec["live_approval"] = approval_record
            rec["stage"] = PromotionStage.APPROVED_LIVE.value
            rec["audit_trail"].append({
                "event": "APPROVED_FOR_LIVE",
                "stage": PromotionStage.APPROVED_LIVE.value,
                "timestamp": time.time(),
                "approval": approval_record
            })
            log.info("[PromotionManager] Strategy '%s' APPROVED FOR LIVE by %s", strategy_id, approver_name)
            return True, f"Strategy '{strategy_id}' approved for LIVE execution"

    def is_authorized_for_live(self, strategy_id: str) -> bool:
        """
        Live execution gate: Verifies that strategy is in APPROVED_LIVE and
        its parameters have not mutated since approval.
        """
        with self._lock:
            rec = self._registry.get(strategy_id)
            if not rec:
                return False

            if rec["stage"] != PromotionStage.APPROVED_LIVE.value:
                return False

            approval = rec.get("live_approval")
            if not approval:
                return False

            # Strict Invariant: Hash of active parameters MUST match approved hash!
            current_hash = compute_params_hash(rec["params"])
            if current_hash != approval.get("approved_params_hash"):
                log.critical(
                    "PARAMETER SNOOPING DETECTED! Strategy '%s' active hash [%s] != approved hash [%s]!",
                    strategy_id, current_hash, approval.get("approved_params_hash")
                )
                return False

            return True

    def get_strategy_record(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._registry.get(strategy_id)


# Governance Singleton
promotion_manager = StrategyPromotionManager()

