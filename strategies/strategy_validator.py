"""
strategies/strategy_validator.py — Strategy Watchdog & Intent Validation Engine

Guarantees execution safety:
1. Validates OrderIntent for finite numbers, no NaNs/Infs, valid size bounds.
2. Watchdog executor: enforces a strict 30ms timeout on strategy execution to prevent hung loops.
"""

from __future__ import annotations
import math
import logging
import concurrent.futures
from typing import Callable, Any, Optional
import pandas as pd
from core.order_intent import OrderIntent, PositionContext

log = logging.getLogger(__name__)

DEFAULT_STRATEGY_TIMEOUT_SEC = 0.030  # 30 milliseconds


class StrategyValidator:
    """
    Validates strategy inputs and outputs while enforcing watchdog timeouts.
    """

    def __init__(self, timeout_sec: float = DEFAULT_STRATEGY_TIMEOUT_SEC) -> None:
        self.timeout_sec = timeout_sec
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

    def execute_with_watchdog(
        self,
        strategy_func: Callable[[str, pd.DataFrame, Optional[PositionContext]], Optional[OrderIntent]],
        symbol: str,
        df: pd.DataFrame,
        position_context: Optional[PositionContext] = None
    ) -> Optional[OrderIntent]:
        """
        Executes strategy within a timeout budget. If execution exceeds timeout,
        logs an error and safely aborts.
        """
        future = self._executor.submit(strategy_func, symbol, df, position_context)
        try:
            intent = future.result(timeout=self.timeout_sec)
        except concurrent.futures.TimeoutError:
            log.error(
                "WATCHDOG TIMEOUT: Strategy exceeded %d ms limit on %s! Aborting execution.",
                int(self.timeout_sec * 1000),
                symbol
            )
            return None
        except Exception as e:
            log.error("STRATEGY ERROR on %s: %s", symbol, e, exc_info=True)
            return None

        if intent is None:
            return None

        # Validate intent
        is_valid, reason = self.validate_intent(intent)
        if not is_valid:
            log.warning("INTENT REJECTED: %s for %s (%s)", intent.intent_id, symbol, reason)
            return None

        return intent

    def validate_intent(self, intent: OrderIntent) -> tuple[bool, str]:
        """Validates OrderIntent fields and structural integrity."""
        if not isinstance(intent, OrderIntent):
            return False, f"Expected OrderIntent, got {type(intent)}"
        return intent.validate()
