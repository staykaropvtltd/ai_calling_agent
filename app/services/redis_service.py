import json
import redis

from app.config.settings import REDIS_URL

redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True
)


def save_call_session(call_id: str, data: dict):
    redis_client.set(
        f"call_session:{call_id}",
        json.dumps(data),
        ex=3600    # Expire after 1 hour
    )


def get_call_session(call_id: str):
    data = redis_client.get(f"call_session:{call_id}")

    if data:
        return json.loads(data)

    return None