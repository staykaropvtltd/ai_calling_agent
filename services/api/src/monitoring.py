"""NH-18 — Monitoring, alerting, and the metrics they're evaluated against.

Infrastructure & Operations Guide §5 draws a hard line between three jobs:
logging (what happened), monitoring (the system's current state), and
alerting (turning "monitoring noticed something bad" into someone actually
finding out, without staring at a dashboard). This module owns the second
and third — logging already exists (src/main.py's request_logging
middleware).

Scope, honestly: the full metrics table in §5 includes active calls,
per-stage voice latency, and provider failure rate — none of which exist
yet, because they depend on the live voice pipeline (SH-04/06/08, blocked
on STT/LLM/TTS provider API keys the user hasn't supplied). What's real and
measurable today without any of that: HTTP error rate, request latency,
and database/Redis reachability — this module covers exactly those three,
plus disk usage on whatever filesystem this process itself sees (the
container's own layer, not the VPS host's — see DiskUsageAlert's docstring).

Also honestly scoped: "alerting" here means turning a breached threshold
into a loud, structured log line (NotifyingAlert / LoggingNotifier below),
not a page to someone's phone. Actually paging (Slack/PagerDuty/SMS) needs
a destination — a webhook URL or API key nobody has supplied — so this
stops at the Notifier Protocol, a pluggable seam a future change can wire a
real destination into without touching the threshold-evaluation logic here.
"""

from __future__ import annotations

import logging
import shutil
import time
from collections import deque
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger("staykaro.monitoring")


# ── Metrics collection ──────────────────────────────────────────────────────


@dataclass
class _Sample:
    at: float  # time.monotonic()
    status_code: int
    elapsed_ms: float


class MetricsRegistry:
    """In-process rolling window of recent HTTP requests.

    In-memory, per-process — correct for this single-instance V1 deployment
    (Infrastructure & Operations Guide §8: "V1 deliberately doesn't scale
    much yet"). A multi-instance deployment would need this centralized
    (e.g. actual Prometheus + a /metrics scrape target per instance) rather
    than each process reporting only what it personally saw.
    """

    def __init__(self, window_seconds: float = 600.0, max_samples: int = 10_000) -> None:
        self._window_seconds = window_seconds
        self._samples: deque[_Sample] = deque(maxlen=max_samples)

    def record(self, status_code: int, elapsed_ms: float) -> None:
        self._samples.append(_Sample(at=time.monotonic(), status_code=status_code, elapsed_ms=elapsed_ms))

    def _recent(self) -> list[_Sample]:
        cutoff = time.monotonic() - self._window_seconds
        # deque, not a list-comprehension-friendly structure for random access,
        # but samples arrive in monotonic order, so trimming from the left is
        # exactly the "drop everything older than the window" operation.
        while self._samples and self._samples[0].at < cutoff:
            self._samples.popleft()
        return list(self._samples)

    def snapshot(self) -> MetricsSnapshot:
        recent = self._recent()
        total = len(recent)
        errors = sum(1 for s in recent if s.status_code >= 500)
        latencies = sorted(s.elapsed_ms for s in recent)
        return MetricsSnapshot(
            window_seconds=self._window_seconds,
            request_count=total,
            error_count=errors,
            error_rate=(errors / total) if total else 0.0,
            p50_latency_ms=_percentile(latencies, 0.50),
            p95_latency_ms=_percentile(latencies, 0.95),
        )


def _percentile(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    idx = min(len(sorted_values) - 1, int(len(sorted_values) * p))
    return sorted_values[idx]


@dataclass
class MetricsSnapshot:
    window_seconds: float
    request_count: int
    error_count: int
    error_rate: float
    p50_latency_ms: float | None
    p95_latency_ms: float | None


# ── Alerting ─────────────────────────────────────────────────────────────────


@dataclass
class Alert:
    signal: str
    message: str
    value: str
    threshold: str
    severity: str = "page"  # "page" (Infra Guide §5's paging rows) or "notify" (non-paging)


class Notifier(Protocol):
    def notify(self, alert: Alert) -> None: ...


class LoggingNotifier:
    """Default notifier — a structured, impossible-to-miss log line.

    Deliberately the ONLY notifier shipped here. Wiring a real destination
    (Slack webhook, PagerDuty, SMS) is an operator decision requiring a
    credential this codebase doesn't have — implement Notifier's one method
    against that destination and pass it into check_and_notify() in place of
    this one; nothing else in this module needs to change.
    """

    def notify(self, alert: Alert) -> None:
        log = logger.critical if alert.severity == "page" else logger.warning
        log(
            "ALERT [%s] %s (value=%s, threshold=%s)",
            alert.signal,
            alert.message,
            alert.value,
            alert.threshold,
        )


# Thresholds transcribed directly from Infrastructure & Operations Guide §5's
# table — change these only if that table changes, not independently.
_ERROR_RATE_THRESHOLD = 0.05  # "> 5% of calls in 10 minutes" (provider failure rate row;
# applied here to HTTP error rate generally, the metric this module actually has)
_LATENCY_P95_THRESHOLD_MS = 1500  # "> 1.5s sustained for 5 minutes" (total response latency p95)
_DISK_USAGE_THRESHOLD_PCT = 85.0  # "> 85%" (non-paging)
_MIN_REQUESTS_FOR_ERROR_RATE_ALERT = 20  # avoid alerting on "1 error out of 1 request"


def _disk_usage_pct(path: str = "/") -> float:
    """Disk usage of the filesystem *this process* sees. Inside a Docker
    container that's the container's own writable layer — a useful proxy
    for "is this service about to fail from ENOSPC", but NOT the same
    number as the VPS host's actual disk usage (Postgres/Redis's data
    volumes are mounted into *different* containers, invisible from here).
    A real "> 85% on the VPS" alert needs a host-level check outside any
    single container; this is the honest subset reachable from inside one.
    """
    usage = shutil.disk_usage(path)
    return (usage.used / usage.total) * 100 if usage.total else 0.0


def check_alerts(
    metrics: MetricsSnapshot,
    *,
    db_status: str,
    redis_status: str,
) -> list[Alert]:
    """Pure function: metrics + dependency health in, breached-threshold
    Alerts out. No I/O, no notification side effects — see check_and_notify
    for that — so this is trivially unit-testable against fabricated inputs."""
    alerts: list[Alert] = []

    if db_status == "unreachable":
        alerts.append(
            Alert(
                signal="database_unreachable",
                message="Database is unreachable",
                value=db_status,
                threshold="any occurrence",
                severity="page",
            )
        )
    if redis_status == "unreachable":
        alerts.append(
            Alert(
                signal="redis_unreachable",
                message="Redis is unreachable",
                value=redis_status,
                threshold="any occurrence",
                severity="page",
            )
        )

    if (
        metrics.request_count >= _MIN_REQUESTS_FOR_ERROR_RATE_ALERT
        and metrics.error_rate > _ERROR_RATE_THRESHOLD
    ):
        alerts.append(
            Alert(
                signal="error_rate",
                message=f"5xx error rate over the last {metrics.window_seconds:.0f}s exceeds threshold",
                value=f"{metrics.error_rate:.1%} ({metrics.error_count}/{metrics.request_count})",
                threshold=f"> {_ERROR_RATE_THRESHOLD:.0%}",
                severity="page",
            )
        )

    if metrics.p95_latency_ms is not None and metrics.p95_latency_ms > _LATENCY_P95_THRESHOLD_MS:
        alerts.append(
            Alert(
                signal="latency_p95",
                message="p95 request latency exceeds threshold",
                value=f"{metrics.p95_latency_ms:.0f}ms",
                threshold=f"> {_LATENCY_P95_THRESHOLD_MS}ms",
                severity="page",
            )
        )

    disk_pct = _disk_usage_pct()
    if disk_pct > _DISK_USAGE_THRESHOLD_PCT:
        alerts.append(
            Alert(
                signal="disk_usage",
                message="Disk usage exceeds threshold",
                value=f"{disk_pct:.1f}%",
                threshold=f"> {_DISK_USAGE_THRESHOLD_PCT:.0f}%",
                severity="notify",
            )
        )

    return alerts


def check_and_notify(
    metrics: MetricsSnapshot,
    *,
    db_status: str,
    redis_status: str,
    notifier: Notifier | None = None,
) -> list[Alert]:
    notifier = notifier or LoggingNotifier()
    alerts = check_alerts(metrics, db_status=db_status, redis_status=redis_status)
    for alert in alerts:
        notifier.notify(alert)
    return alerts


registry = MetricsRegistry()
