import json

import redis

from app.config.settings import REDIS_URL


redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
)


def save_call_session(call_id: str, data: dict):
    try:
        redis_client.set(
            f"call_session:{call_id}",
            json.dumps(data),
            ex=3600,
        )
    except redis.RedisError as e:
        print(f"Redis Error: {e}")


def get_call_session(call_id: str):
    try:
        data = redis_client.get(f"call_session:{call_id}")
    except redis.RedisError as e:
        print(f"Redis Error: {e}")
        return None

    if data:
        return json.loads(data)

    return None


def update_call_session(call_id: str, status: str):
    try:
        session = get_call_session(call_id)

        if session:
            session["status"] = status

            redis_client.set(
                f"call_session:{call_id}",
                json.dumps(session),
                ex=3600,
            )

    except redis.RedisError as e:
        print(f"Redis Error: {e}")
