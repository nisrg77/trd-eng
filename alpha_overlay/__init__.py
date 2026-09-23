"""
alpha_overlay — Institutional Footprint & Flow (IFF) + Predictive Microstructure overlay.

Modules:
    vap_cvd   : Volume-at-Price histogram and Cumulative Volume Delta tracker.
    cot_bias  : CFTC COT macro structural bias (Phase 5 stub, returns 0.0).
    iff       : Composite S_flow score combining CVD divergence, OBI, and COT.
"""

from alpha_overlay.iff import get_flow_score, apply_iff_gate
from alpha_overlay.vap_cvd import get_vpoc, get_vah_val, get_cvd, get_predictive_signal
from alpha_overlay.cot_bias import get_cot_zscore

__all__ = [
    "get_flow_score",
    "apply_iff_gate",
    "get_vpoc",
    "get_vah_val",
    "get_cvd",
    "get_predictive_signal",
    "get_cot_zscore",
]
