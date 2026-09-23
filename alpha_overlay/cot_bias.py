"""
alpha_overlay/cot_bias.py — CFTC COT Macro Structural Bias

Phase 5 stub. Returns 0.0 for all symbols until a confirmed CFTC data
source is integrated (see chng.md §6 Phase 5 and §7 Q2).

When implemented, this module will:
  • Fetch CFTC disaggregated futures reports weekly (Friday 3:30 PM EST).
  • Maintain a rolling 52-week z-score of "Managed Money" net positions.
  • Map crypto instruments to CME BTC/ETH futures as a proxy
    (flagged as proxy=True so downstream weights can discount it).
  • Expose get_cot_zscore(symbol) → float ∈ roughly [-3, +3].

TODO Phase 5: Implement CFTC data ingestion and Z_COT computation.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def get_cot_zscore(symbol: str) -> float:
    """
    Returns the CFTC COT z-score for the given symbol.

    Phase 5 stub — always returns 0.0.
    A positive value indicates net-long managed-money positioning (bullish bias);
    negative indicates net-short (bearish bias).
    """
    # TODO Phase 5: fetch weekly CFTC disaggregated data, compute 52-week z-score
    return 0.0
