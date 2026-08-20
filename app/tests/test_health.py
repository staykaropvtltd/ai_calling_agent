from unittest.mock import AsyncMock, MagicMock, patch

import redis
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from main import app

client = TestClient(app)


def _async_engine(pg_error=None):
    """Return a mock async engine; pg_error is raised on connection enter."""
    cm = AsyncMock()
    if pg_error:
        cm.__aenter__.side_effect = pg_error
    engine = MagicMock()
    engine.connect.return_value = cm
    return engine


def test_health():
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_when_dependencies_are_healthy():
    with (
        patch("app.routers.health.engine", _async_engine()),
        patch("app.routers.health.redis_client.ping") as mock_ping,
    ):
        response = client.get("/api/v1/health/ready")

        assert response.status_code == 200
        assert response.json() == {"status": "ready", "checks": {"postgresql": "ok", "redis": "ok"}}

        mock_ping.assert_called_once()


def test_readiness_when_postgresql_is_unavailable():
    with (
        patch(
            "app.routers.health.engine",
            _async_engine(pg_error=SQLAlchemyError("PostgreSQL unavailable")),
        ),
        patch("app.routers.health.redis_client.ping"),
    ):
        response = client.get("/api/v1/health/ready")

        assert response.status_code == 503
        assert response.json() == {
            "status": "not_ready",
            "checks": {"postgresql": "error", "redis": "ok"},
        }


def test_readiness_when_redis_is_unavailable():
    with (
        patch("app.routers.health.engine", _async_engine()),
        patch(
            "app.routers.health.redis_client.ping",
            side_effect=redis.RedisError("Redis unavailable"),
        ),
    ):
        response = client.get("/api/v1/health/ready")

        assert response.status_code == 503
        assert response.json() == {
            "status": "not_ready",
            "checks": {"postgresql": "ok", "redis": "error"},
        }


def test_liveness_when_dependencies_are_unavailable():
    with (
        patch(
            "app.routers.health.engine",
            _async_engine(pg_error=SQLAlchemyError("PostgreSQL unavailable")),
        ),
        patch(
            "app.routers.health.redis_client.ping",
            side_effect=redis.RedisError("Redis unavailable"),
        ),
    ):
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
