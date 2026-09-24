"""
middleware/system_monitor.py — Real-Time Production System Monitoring & Alerts

Provides critical operational telemetry:
1. Feed Lag Monitoring: Detects stale data feeds and clock drift.
2. Order Reject & Fill Rate Tracking: Alerts on sudden reject spikes.
3. Position Reconciliation Checking: Detects mismatches between local state and exchange ground truth.
4. Watchdog Heartbeat: Alerts when the feed or system goes quiet (> 15s).
5. Central Alert Bus with severity levels (INFO, WARNING, CRITICAL).
"""

from __future__ import annotations
import time
import uuid
import logging
import threading
from enum import Enum
from typing import Dict, Any, List, Optional
from collections import deque
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class SystemAlert:
    alert_id: str
    severity: AlertSeverity
    alert_type: str
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "severity": self.severity.value,
            "alert_type": self.alert_type,
            "message": self.message,
            "data": self.data,
            "timestamp": self.timestamp
        }


class SystemMonitor:
    """
    Production health monitor for data feed lag, execution safety, and reconciliation.
    """

    def __init__(
        self,
        max_feed_lag_sec: float = 2.0,
        heartbeat_timeout_sec: float = 15.0,
        max_reject_rate: float = 0.25,
        max_alerts_history: int = 500
    ) -> None:
        self.max_feed_lag_sec = max_feed_lag_sec
        self.heartbeat_timeout_sec = heartbeat_timeout_sec
        self.max_reject_rate = max_reject_rate
        
        self._lock = threading.RLock()
        self._last_event_time = time.time()
        self._feed_last_seen: Dict[str, float] = {}
        self._recent_orders: deque[bool] = deque(maxlen=40)  # True = fill, False = reject
        self._alerts: deque[SystemAlert] = deque(maxlen=max_alerts_history)

    # ── Alerts ───────────────────────────────────────────────────────────────
    def raise_alert(
        self,
        severity: AlertSeverity | str,
        alert_type: str,
        message: str,
        data: Optional[Dict[str, Any]] = None
    ) -> SystemAlert:
        """Publishes an alert to the log and alert queue."""
        if isinstance(severity, str):
            severity = AlertSeverity(severity.upper())

        with self._lock:
            alert = SystemAlert(
                alert_id=f"alt_{uuid.uuid4().hex[:8]}",
                severity=severity,
                alert_type=alert_type,
                message=message,
                data=data or {}
            )
            self._alerts.append(alert)

            log_fn = log.info
            if severity == AlertSeverity.WARNING:
                log_fn = log.warning
            elif severity == AlertSeverity.CRITICAL:
                log_fn = log.critical

            log_fn(f"[ALERT:{severity.value}] [{alert_type}] {message} | {data}")
            return alert

    def get_recent_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return [a.to_dict() for a in list(self._alerts)[-limit:]]

    # ── Feed Lag & Heartbeat ──────────────────────────────────────────────────
    def record_feed_tick(self, symbol: str, tick_timestamp: float) -> Optional[SystemAlert]:
        """
        Records an incoming market tick and checks for feed latency lag.
        """
        now = time.time()
        with self._lock:
            self._last_event_time = now
            self._feed_last_seen[symbol] = now

            lag_sec = now - tick_timestamp
            if lag_sec > self.max_feed_lag_sec:
                return self.raise_alert(
                    severity=AlertSeverity.WARNING,
                    alert_type="FEED_LAG_DETECTED",
                    message=f"Feed lag on {symbol}: {lag_sec:.2f}s exceeds limit {self.max_feed_lag_sec:.2f}s",
                    data={"symbol": symbol, "lag_sec": round(lag_sec, 3)}
                )
        return None

    def check_heartbeat(self) -> Optional[SystemAlert]:
        """
        Watchdog: Checks if the system has gone quiet without ticks or events.
        """
        now = time.time()
        with self._lock:
            quiet_sec = now - self._last_event_time
            if quiet_sec > self.heartbeat_timeout_sec:
                return self.raise_alert(
                    severity=AlertSeverity.CRITICAL,
                    alert_type="SYSTEM_QUIET_HEARTBEAT",
                    message=f"System has been quiet for {quiet_sec:.1f}s (> {self.heartbeat_timeout_sec:.1f}s)!",
                    data={"quiet_duration_sec": round(quiet_sec, 2)}
                )
        return None

    # ── Order Outcomes & Rejects ─────────────────────────────────────────────
    def record_order_outcome(
        self,
        symbol: str,
        strategy_id: str,
        success: bool,
        error: Optional[str] = None
    ) -> Optional[SystemAlert]:
        """
        Tracks order execution successes and rejections. Alerts if reject rate spikes.
        """
        with self._lock:
            self._last_event_time = time.time()
            self._recent_orders.append(success)

            if not success:
                self.raise_alert(
                    severity=AlertSeverity.WARNING,
                    alert_type="ORDER_REJECTED",
                    message=f"Order rejected on {symbol} by {strategy_id}: {error}",
                    data={"symbol": symbol, "strategy_id": strategy_id, "error": error}
                )

            # Check reject rate spike over rolling window
            if len(self._recent_orders) >= 10:
                rejects = self._recent_orders.count(False)
                rate = rejects / len(self._recent_orders)
                if rate >= self.max_reject_rate:
                    return self.raise_alert(
                        severity=AlertSeverity.CRITICAL,
                        alert_type="HIGH_REJECT_RATE",
                        message=f"Order reject rate spiked to {rate:.1%} ({rejects}/{len(self._recent_orders)})!",
                        data={"reject_rate": rate, "rejects": rejects, "total": len(self._recent_orders)}
                    )
        return None

    # ── Position Reconciliation Checking ─────────────────────────────────────
    def check_reconciliation(
        self,
        local_positions: Dict[str, float],
        exchange_positions: Dict[str, float],
        tolerance: float = 1e-4
    ) -> tuple[bool, List[str]]:
        """
        Compares local position cache with exchange ground truth.
        Returns (is_synced: bool, discrepancies: List[str]).
        """
        discrepancies: List[str] = []
        all_symbols = set(local_positions.keys()).union(set(exchange_positions.keys()))

        with self._lock:
            for sym in all_symbols:
                local_qty = local_positions.get(sym, 0.0)
                exch_qty = exchange_positions.get(sym, 0.0)
                diff = abs(local_qty - exch_qty)

                if diff > tolerance:
                    msg = f"Position mismatch on {sym}: Local={local_qty}, Exchange={exch_qty} (diff={diff:.4f})"
                    discrepancies.append(msg)

            if discrepancies:
                self.raise_alert(
                    severity=AlertSeverity.CRITICAL,
                    alert_type="RECONCILIATION_MISMATCH",
                    message=f"Found {len(discrepancies)} position reconciliation mismatches with exchange!",
                    data={"discrepancies": discrepancies}
                )
                return False, discrepancies

            return True, []


# Global system monitor instance
system_monitor = SystemMonitor()
