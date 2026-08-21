import json
from unittest.mock import patch

import redis

from app.services.redis_service import (
    get_call_session,
    save_call_session,
    update_call_session,
)


def test_save_call_session():
    with patch("app.services.redis_service.redis_client.set") as mock_set:
        data = {"customer_name": "John", "status": "initiated"}

        save_call_session("123", data)

        mock_set.assert_called_once()


def test_get_call_session():
    sample = {"customer_name": "John", "status": "completed"}

    with patch("app.services.redis_service.redis_client.get", return_value=json.dumps(sample)):
        result = get_call_session("123")

        assert result["customer_name"] == "John"
        assert result["status"] == "completed"


def test_update_call_session():
    session = {"customer_name": "John", "status": "initiated"}

    with (
        patch("app.services.redis_service.get_call_session", return_value=session),
        patch("app.services.redis_service.redis_client.set") as mock_set,
    ):
        update_call_session("123", "completed")
        mock_set.assert_called_once()


def test_missing_call_session():
    with patch("app.services.redis_service.redis_client.get", return_value=None):
        result = get_call_session("123")

        assert result is None


def test_redis_failure():
    with patch(
        "app.services.redis_service.redis_client.get", side_effect=redis.RedisError("Redis Down")
    ):
        result = get_call_session("123")

        assert result is None
