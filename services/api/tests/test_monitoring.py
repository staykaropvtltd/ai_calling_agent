"""
NH-18 — monitoring metrics + alert-threshold evaluation.

Thresholds are transcribed from Infrastructure & Operations Guide §5's
table — these tests check the evaluation logic against fabricated metrics,
not against a live system (no real error-rate spike or disk-full condition
exists in a test run). See src/monitoring.py's module docstring for what's
deliberately out of scope here (per-stage voice latency, provider failure
rate — both need the live voice pipeline; actual paging — needs a
destination credential nobody has supplied).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from src.monitoring import Alert, MetricsRegistry, MetricsSnapshot, check_alerts


def _snapshot(**overrides) -> MetricsSnapshot:
    base = {
        "window_seconds": 600,
        "request_count": 100,
        "error_count": 0,
        "error_rate": 0.0,
        "p50_latency_ms": 50.0,
        "p95_latency_ms": 100.0,
    }
    base.update(overrides)
    return MetricsSnapshot(**base)


class TestMetricsRegistry:
    def test_empty_registry_snapshot(self):
        reg = MetricsRegistry()
        snap = reg.snapshot()
        assert snap.request_count == 0
        assert snap.error_rate == 0.0
        assert snap.p95_latency_ms is None

    def test_records_error_rate_and_latency(self):
        reg = MetricsRegistry()
        for _ in range(8):
            reg.record(200, 50.0)
        for _ in range(2):
            reg.record(500, 200.0)

        snap = reg.snapshot()
        assert snap.request_count == 10
        assert snap.error_count == 2
        assert snap.error_rate == pytest.approx(0.2)

    def test_window_drops_stale_samples(self, monkeypatch):
        import time as _time

        reg = MetricsRegistry(window_seconds=10)
        t = [1000.0]
        monkeypatch.setattr(_time, "monotonic", lambda: t[0])
        reg.record(200, 10.0)

        t[0] += 20  # past the 10s window
        reg.record(200, 10.0)

        snap = reg.snapshot()
        assert snap.request_count == 1  # only the second sample survives


class TestCheckAlerts:
    def test_no_alerts_when_everything_healthy(self):
        alerts = check_alerts(
            _snapshot(), db_status="ok", redis_status="ok", disk_usage_pct_fn=lambda: 10.0
        )
        assert alerts == []

    def test_database_unreachable_pages(self):
        alerts = check_alerts(_snapshot(), db_status="unreachable", redis_status="ok")
        signals = [a.signal for a in alerts]
        assert "database_unreachable" in signals
        assert next(a for a in alerts if a.signal == "database_unreachable").severity == "page"

    def test_redis_unreachable_pages(self):
        alerts = check_alerts(_snapshot(), db_status="ok", redis_status="unreachable")
        assert any(a.signal == "redis_unreachable" for a in alerts)

    def test_redis_not_configured_does_not_alert(self):
        """not_configured is a deliberate degraded-but-functional mode
        (src/main.py's own health check treats it the same way) — never a
        page-worthy outage."""
        alerts = check_alerts(
            _snapshot(),
            db_status="ok",
            redis_status="not_configured",
            disk_usage_pct_fn=lambda: 10.0,
        )
        assert alerts == []

    def test_high_error_rate_pages(self):
        snap = _snapshot(request_count=100, error_count=10, error_rate=0.10)
        alerts = check_alerts(snap, db_status="ok", redis_status="ok")
        assert any(a.signal == "error_rate" for a in alerts)

    def test_error_rate_below_threshold_does_not_alert(self):
        snap = _snapshot(request_count=100, error_count=2, error_rate=0.02)
        alerts = check_alerts(snap, db_status="ok", redis_status="ok")
        assert not any(a.signal == "error_rate" for a in alerts)

    def test_high_error_rate_with_too_few_requests_does_not_alert(self):
        """1 error out of 1 request is a 100% error rate but not a
        meaningful signal — avoids paging on statistical noise."""
        snap = _snapshot(request_count=1, error_count=1, error_rate=1.0)
        alerts = check_alerts(snap, db_status="ok", redis_status="ok")
        assert not any(a.signal == "error_rate" for a in alerts)

    def test_high_latency_pages(self):
        snap = _snapshot(p95_latency_ms=2000.0)
        alerts = check_alerts(snap, db_status="ok", redis_status="ok")
        assert any(a.signal == "latency_p95" for a in alerts)

    def test_no_latency_data_does_not_alert(self):
        snap = _snapshot(p95_latency_ms=None)
        alerts = check_alerts(snap, db_status="ok", redis_status="ok")
        assert not any(a.signal == "latency_p95" for a in alerts)

    def test_multiple_simultaneous_breaches_all_reported(self):
        snap = _snapshot(request_count=100, error_count=50, error_rate=0.5, p95_latency_ms=5000.0)
        alerts = check_alerts(
            snap,
            db_status="unreachable",
            redis_status="unreachable",
            disk_usage_pct_fn=lambda: 10.0,
        )
        signals = {a.signal for a in alerts}
        assert signals == {"database_unreachable", "redis_unreachable", "error_rate", "latency_p95"}

    def test_disk_usage_above_threshold_pages(self):
        alerts = check_alerts(
            _snapshot(), db_status="ok", redis_status="ok", disk_usage_pct_fn=lambda: 90.0
        )
        assert any(a.signal == "disk_usage" for a in alerts)
        assert next(a for a in alerts if a.signal == "disk_usage").severity == "notify"

    def test_disk_usage_below_threshold_does_not_alert(self):
        alerts = check_alerts(
            _snapshot(), db_status="ok", redis_status="ok", disk_usage_pct_fn=lambda: 50.0
        )
        assert not any(a.signal == "disk_usage" for a in alerts)

    def test_disk_usage_real_function_works(self):
        """_get_disk_usage_pct returns a real value and doesn't raise."""
        from src.monitoring import _get_disk_usage_pct

        pct = _get_disk_usage_pct()
        assert isinstance(pct, float)
        assert 0.0 <= pct <= 100.0


class TestLoggingNotifier:
    def test_page_severity_logs_critical(self, caplog):
        from src.monitoring import LoggingNotifier

        with caplog.at_level("CRITICAL", logger="staykaro.monitoring"):
            LoggingNotifier().notify(
                Alert(signal="x", message="m", value="v", threshold="t", severity="page")
            )
        assert any("ALERT" in r.message for r in caplog.records)
        assert any(r.levelname == "CRITICAL" for r in caplog.records)

    def test_notify_severity_logs_warning_not_critical(self, caplog):
        from src.monitoring import LoggingNotifier

        with caplog.at_level("WARNING", logger="staykaro.monitoring"):
            LoggingNotifier().notify(
                Alert(signal="x", message="m", value="v", threshold="t", severity="notify")
            )
        assert any(r.levelname == "WARNING" for r in caplog.records)
        assert not any(r.levelname == "CRITICAL" for r in caplog.records)


# ── GET /metrics endpoint ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_metrics_requires_super_admin(api_client: AsyncClient, user_headers: dict):
    r = await api_client.get("/metrics", headers=user_headers)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_metrics_rejects_unauthenticated(api_client: AsyncClient):
    r = await api_client.get("/metrics")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_metrics_returns_snapshot_for_super_admin(
    api_client: AsyncClient, super_admin_headers: dict
):
    r = await api_client.get("/metrics", headers=super_admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert "request_count" in body
    assert "error_rate" in body
    assert "db" in body
    assert "redis" in body
