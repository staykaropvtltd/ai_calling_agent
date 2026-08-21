"""Transcript consumer for SH-04 → SH-06 handoff (transcript_handler.py).

Provides a factory that returns an on_transcript callback wired to a call_id.
The callback:
  - Appends every TranscriptEvent to Redis list ``transcript:{call_id}``
    (both interim and final, flagged by is_final).
  - Logs at INFO for final, DEBUG for interim — never logs raw transcript text.
  - Never propagates exceptions: Redis failures are isolated from the audio path.
  - SH-06 reads ``transcript:{call_id}`` from Redis and processes final entries.

Redis key schema (no new API/schema needed — extends existing call_session pattern):
  transcript:{call_id}   Redis list, RPUSH, TTL 3600 s
  Each element: JSON {"seq": int, "ts": ISO-8601, "transcript": str,
                       "is_final": bool, "confidence": float}
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import redis.asyncio as aioredis

from packages.providers.stt import TranscriptEvent

logger = logging.getLogger(__name__)

# Redis TTL for transcript lists — matches the session TTL in redis_service.py.
_TRANSCRIPT_TTL_S = 3600


def _get_redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def make_transcript_handler(
    call_id: str,
    redis_url: str | None = None,
) -> Callable[[TranscriptEvent], Awaitable[None]]:
    """Return a coroutine function that persists each TranscriptEvent to Redis.

    Args:
        call_id: The internal call identifier, used as part of the Redis key.
        redis_url: Override the REDIS_URL env-var (for tests).

    Returns:
        An ``async def on_transcript(event)`` callback safe to pass to
        ``CallPipelineHandle(on_transcript=...)``.
    """
    _url = redis_url or _get_redis_url()
    _redis: aioredis.Redis | None = None
    _seq = 0
    _redis_key = f"transcript:{call_id}"

    async def _get_client() -> aioredis.Redis:
        nonlocal _redis
        if _redis is None:
            _redis = aioredis.from_url(_url, decode_responses=True)
        return _redis

    async def on_transcript(event: TranscriptEvent) -> None:
        nonlocal _seq
        _seq += 1
        entry = {
            "seq": _seq,
            "ts": datetime.now(timezone.utc).isoformat(),
            "transcript": event.transcript,
            "is_final": event.is_final,
            "confidence": event.confidence,
        }
        # Log at INFO for final (retained), DEBUG for interim (ephemeral).
        # Never log the raw transcript text — it may contain sensitive speech.
        if event.is_final:
            logger.info(
                "Final transcript received",
                extra={"call_id": call_id, "seq": _seq, "confidence": event.confidence},
            )
        else:
            logger.debug(
                "Interim transcript received",
                extra={"call_id": call_id, "seq": _seq},
            )

        try:
            client = await _get_client()
            await client.rpush(_redis_key, json.dumps(entry))
            # Reset TTL on every push so the list survives for at least 1 hour
            # from the last speech event.
            await client.expire(_redis_key, _TRANSCRIPT_TTL_S)
        except Exception as exc:
            # Redis failures MUST NOT break the audio or STT pipeline.
            logger.warning(
                "Transcript Redis write failed; event dropped",
                extra={"call_id": call_id, "seq": _seq, "error": str(exc)},
            )

    return on_transcript
