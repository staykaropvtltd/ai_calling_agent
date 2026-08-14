from unittest.mock import MagicMock, patch

import redis
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from main import app


client = TestClient(app)


def test_health():
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok"
    }


def test_readiness_when_dependencies_are_healthy():
    with patch("app.routers.health.engine.connect") as mock_connect:
        with patch("app.routers.health.redis_client.ping") as mock_ping:

            mock_connection = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_connection

            response = client.get("/api/v1/health/ready")

            assert response.status_code == 200
            assert response.json() == {
                "status": "ready",
                "checks": {
                    "postgresql": "ok",
                    "redis": "ok"
                }
            }

            mock_ping.assert_called_once()


def test_readiness_when_postgresql_is_unavailable():
    with patch(
        "app.routers.health.engine.connect",
        side_effect=SQLAlchemyError("PostgreSQL unavailable")
    ):
        with patch("app.routers.health.redis_client.ping"):

            response = client.get("/api/v1/health/ready")

            assert response.status_code == 503
            assert response.json() == {
                "status": "not_ready",
                "checks": {
                    "postgresql": "error",
                    "redis": "ok"
                }
            }


def test_readiness_when_redis_is_unavailable():
    with patch("app.routers.health.engine.connect") as mock_connect:
        with patch(
            "app.routers.health.redis_client.ping",
            side_effect=redis.RedisError("Redis unavailable")
        ):

            mock_connection = MagicMock()
            mock_connect.return_value.__enter__.return_value = mock_connection

            response = client.get("/api/v1/health/ready")

            assert response.status_code == 503
            assert response.json() == {
                "status": "not_ready",
                "checks": {
                    "postgresql": "ok",
                    "redis": "error"
                }
            }


def test_liveness_when_dependencies_are_unavailable():
    with patch(
        "app.routers.health.engine.connect",
        side_effect=SQLAlchemyError("PostgreSQL unavailable")
    ):
        with patch(
            "app.routers.health.redis_client.ping",
            side_effect=redis.RedisError("Redis unavailable")
        ):

            response = client.get("/api/v1/health")

            assert response.status_code == 200
            assert response.json() == {
                "status": "ok"
            }