"""
research/rl/export_onnx.py — Frozen Policy ONNX Exporter & Parity Verification

Exports SB3 PPO policies to frozen ONNX graphs for inference in the live kernel:
1. Extracts policy actor network and exports to model.onnx with dynamic batch axes.
2. Emits model_meta.json containing:
   - Ordered feature names
   - Normalization stats (mean, std)
   - Deterministic feature-schema hash (SHA-256)
   - Training config hash (SHA-256)
   - Git commit hash
   - Training seed
   - Training data date range
3. Rigorous Parity Test: Compares SB3 predict() vs. onnxruntime on 1,000 observations.
"""

from __future__ import annotations
import os
import sys
import json
import time
import hashlib
import logging
from typing import Dict, Any, Optional, Tuple, List

import numpy as np
import torch
import torch.nn as nn
import onnxruntime as ort
from stable_baselines3 import PPO

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from research.rl.trading_env import (
    ALL_FEATURE_NAMES,
    MARKET_FEATURE_NAMES,
    POSITION_FEATURE_NAMES,
    ObservationNormalizer
)
from research.rl.train_rl import get_git_revision_hash

log = logging.getLogger(__name__)


class SB3PolicyOnnxWrapper(nn.Module):
    """
    PyTorch wrapper exposing only the actor forward path for ONNX export.
    Outputs action logits for the 3 discrete actions {Short, Flat, Long}.
    """

    def __init__(self, policy: nn.Module) -> None:
        super().__init__()
        self.policy = policy

    def forward(self, observation: torch.Tensor) -> torch.Tensor:
        # Extract features (identity for 1D Box observation vector)
        features = self.policy.extract_features(observation)
        # Pass through policy latent layers
        latent_pi = self.policy.mlp_extractor.forward_actor(features)
        # Output action logits
        action_logits = self.policy.action_net(latent_pi)
        return action_logits


def compute_schema_hash(feature_names: List[str]) -> str:
    """Computes a deterministic SHA-256 hash of the exact ordered feature schema."""
    encoded = json.dumps(feature_names).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def compute_config_hash(config_dict: Dict[str, Any]) -> str:
    """Computes a deterministic SHA-256 hash of training configurations."""
    encoded = json.dumps(config_dict, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def export_policy_to_onnx(
    model: PPO,
    normalizer: ObservationNormalizer,
    output_dir: str,
    training_config: Optional[Dict[str, Any]] = None,
    seed: int = 42,
    data_date_range: Optional[Dict[str, str]] = None,
    model_name: str = "model"
) -> Tuple[str, str]:
    """
    Exports SB3 PPO policy to frozen ONNX model and writes model_meta.json.
    
    Returns:
        Tuple of (onnx_path, meta_path)
    """
    os.makedirs(output_dir, exist_ok=True)
    onnx_path = os.path.join(output_dir, f"{model_name}.onnx")
    meta_path = os.path.join(output_dir, f"{model_name}_meta.json")

    # 1. Wrap policy for deterministic evaluation
    wrapper = SB3PolicyOnnxWrapper(model.policy)
    wrapper.eval()

    feature_names = list(normalizer.feature_names) + list(POSITION_FEATURE_NAMES) if hasattr(normalizer, "feature_names") else list(ALL_FEATURE_NAMES)
    dummy_input = torch.randn(1, len(feature_names), dtype=torch.float32)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # 2. Export to ONNX (using classic TorchScript export for rock-solid stability)
    torch.onnx.export(
        wrapper,
        dummy_input,
        onnx_path,
        export_params=True,
        opset_version=14,
        do_constant_folding=True,
        input_names=["observation"],
        output_names=["action_logits"],
        dynamic_axes={
            "observation": {0: "batch_size"},
            "action_logits": {0: "batch_size"}
        },
        dynamo=False
    )
    log.info("[ExportONNX] Exported ONNX policy to %s", onnx_path)

    # 3. Build model_meta.json
    schema_hash = compute_schema_hash(feature_names)
    config_dict = training_config or {}
    config_hash = compute_config_hash(config_dict)
    git_hash = get_git_revision_hash()
    date_range = data_date_range or {"start": "2026-01-01", "end": "2026-09-01"}

    meta_content = {
        "model_name": model_name,
        "feature_names": feature_names,
        "market_features": normalizer.feature_names if hasattr(normalizer, "feature_names") else MARKET_FEATURE_NAMES,
        "feature_schema_hash": schema_hash,
        "training_config_hash": config_hash,
        "git_hash": git_hash,
        "seed": seed,
        "data_date_range": date_range,
        "normalization_stats": normalizer.stats,
        "action_mapping": {
            "0": "SHORT",
            "1": "FLAT",
            "2": "LONG"
        },
        "observation_dim": len(feature_names),
        "exported_at": time.time(),
        "exported_at_iso": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    }

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta_content, f, indent=2)

    log.info("[ExportONNX] Written metadata to %s (Schema Hash: %s)", meta_path, schema_hash)
    return onnx_path, meta_path


def verify_onnx_parity(
    model: PPO,
    onnx_path: str,
    n_samples: int = 1000,
    tolerance: float = 1e-4,
    seed: int = 42
) -> Tuple[bool, float]:
    """
    Verifies that onnxruntime inference produces outputs matching SB3 predict()
    within tolerance on n_samples random observations.
    
    Returns:
        (passed: bool, max_difference: float)
    """
    np.random.seed(seed)
    session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])

    # Generate random test observations within normal range [-3.0, 3.0]
    test_obs = np.random.uniform(-3.0, 3.0, size=(n_samples, len(ALL_FEATURE_NAMES))).astype(np.float32)

    # 1. SB3 Policy Predict (deterministic)
    sb3_actions, _ = model.predict(test_obs, deterministic=True)

    # 2. ONNX Runtime Predict
    onnx_logits = session.run(None, {"observation": test_obs})[0]
    onnx_actions = np.argmax(onnx_logits, axis=-1)

    # 3. PyTorch raw logits comparison
    with torch.no_grad():
        wrapper = SB3PolicyOnnxWrapper(model.policy)
        wrapper.eval()
        torch_logits = wrapper(torch.from_numpy(test_obs)).numpy()

    # Compare logits difference
    max_logit_diff = float(np.max(np.abs(torch_logits - onnx_logits)))
    action_mismatches = int(np.sum(sb3_actions != onnx_actions))

    log.info(
        "[ParityTest] Evaluated %d samples. Max logit diff: %.6f, Action mismatches: %d",
        n_samples, max_logit_diff, action_mismatches
    )

    passed = (action_mismatches == 0) and (max_logit_diff <= tolerance)
    return passed, max_logit_diff
