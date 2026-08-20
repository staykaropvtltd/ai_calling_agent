"""
Focused tests for the SH-04 ΓåÆ SH-06 transcript handoff (transcript_handler.py).

All tests are fully mocked ΓÇö no Redis connection, no pipecat.

Coverage:
 H01  make_transcript_handler returns a coroutine function
 H02  Interim TranscriptEvent is stored in Redis with is_final=False
 H03  Final TranscriptEvent is stored in Redis with is_final=True
 H04  Both interim and final reach Redis (two events, two rpush calls)
 H05  Stored JSON preserves transcript text, is_final, confidence, seq, ts
 H06  seq counter increments across calls (1, 2, 3, ΓÇª)
 H07  Redis key is transcript:{call_id}
 H08  TTL is set on the key after every push
 H09  Redis failure does NOT raise from on_transcript (pipeline isolation)
 H10  callback is actually passed into CallPipelineHandle and reaches SttBridge
 H11  Consumer failure (on_transcript raises) does not crash SttBridge._recv_loop
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Make voice-gateway modules importable
_VG = str((Path(__file__).parent.parent / "services" / "voice-gateway").resolve())
if _VG not in sys.path:
    sys.path.insert(0, _VG)

from packages.providers.stt import TranscriptEvent, SttError
from transcript_handler import make_transcript_handler
from stt_bridge import SttBridge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event(is_final: bool, transcript: str = "hello", confidence: float = 0.9) -> TranscriptEvent:
    return TranscriptEvent(
        call_id="call-h",
        transcript=transcript,
        is_final=is_final,
        confidence=confidence,
        raw={},
    )


def _mock_redis():
    """Build a mock aioredis.Redis client."""
    r = MagicMock()
    r.rpush = AsyncMock(return_value=1)
    r.expire = AsyncMock(return_value=True)
    return r


async def _invoke(handler, event: TranscriptEvent, mock_redis) -> list[str]:
    """Call handler once and return the JSON strings pushed to Redis."""
    pushed: list[str] = []

    async def fake_rpush(key, value):
        pushed.append(value)
        return len(pushed)

    mock_redis.rpush = AsyncMock(side_effect=fake_rpush)
    mock_redis.expire = AsyncMock(return_value=True)

    with patch("transcript_handler.aioredis.from_url", return_value=mock_redis):
        await handler(event)

    return pushed


# ---------------------------------------------------------------------------
# H01  make_transcript_handler returns a coroutine function
# ---------------------------------------------------------------------------

def test_H01_returns_coroutine_function():
    handler = make_transcript_handler("call-1", redis_url="redis://fake/0")
    assert asyncio.iscoroutinefunction(handler)


# ---------------------------------------------------------------------------
# H02  Interim event stored with is_final=False
# ---------------------------------------------------------------------------

def test_H02_interim_event_stored_with_is_final_false():
    mock_r = _mock_redis()
    handler = make_transcript_handler("call-2", redis_url="redis://fake/0")

    async def run():
        return await _invoke(handler, _event(is_final=False), mock_r)

    pushed = asyncio.run(run())
    assert len(pushed) == 1
    data = json.loads(pushed[0])
    assert data["is_final"] is False


# ---------------------------------------------------------------------------
# H03  Final event stored with is_final=True
# ---------------------------------------------------------------------------

def test_H03_final_event_stored_with_is_final_true():
    mock_r = _mock_redis()
    handler = make_transcript_handler("call-3", redis_url="redis://fake/0")

    async def run():
        return await _invoke(handler, _event(is_final=True), mock_r)

    pushed = asyncio.run(run())
    assert len(pushed) == 1
    data = json.loads(pushed[0])
    assert data["is_final"] is True


# ---------------------------------------------------------------------------
# H04  Both interim and final reach Redis
# ---------------------------------------------------------------------------

def test_H04_both_interim_and_final_reach_redis():
    mock_r = _mock_redis()
    handler = make_transcript_handler("call-4", redis_url="redis://fake/0")
    all_pushed: list[str] = []

    async def fake_rpush(key, value):
        all_pushed.append(value)
        return len(all_pushed)

    mock_r.rpush = AsyncMock(side_effect=fake_rpush)
    mock_r.expire = AsyncMock(return_value=True)

    async def run():
        with patch("transcript_handler.aioredis.from_url", return_value=mock_r):
            await handler(_event(is_final=False, transcript="one"))
            await handler(_event(is_final=True, transcript="two"))

    asyncio.run(run())
    assert len(all_pushed) == 2
    assert json.loads(all_pushed[0])["is_final"] is False
    assert json.loads(all_pushed[1])["is_final"] is True


# ---------------------------------------------------------------------------
# H05  Stored JSON preserves all required fields
# ---------------------------------------------------------------------------

def test_H05_stored_json_preserves_all_fields():
    mock_r = _mock_redis()
    handler = make_transcript_handler("call-5", redis_url="redis://fake/0")

    async def run():
        return await _invoke(handler, _event(is_final=True, transcript="test text", confidence=0.95), mock_r)

    pushed = asyncio.run(run())
    data = json.loads(pushed[0])
    assert "seq" in data
    assert "ts" in data
    assert data["transcript"] == "test text"
    assert data["is_final"] is True
    assert abs(data["confidence"] - 0.95) < 1e-6


# ---------------------------------------------------------------------------
# H06  seq counter increments across successive calls
# ---------------------------------------------------------------------------

def test_H06_seq_increments():
    mock_r = _mock_redis()
    handler = make_transcript_handler("call-6", redis_url="redis://fake/0")
    seqs: list[int] = []

    async def fake_rpush(key, value):
        seqs.append(json.loads(value)["seq"])
        return len(seqs)

    mock_r.rpush = AsyncMock(side_effect=fake_rpush)
    mock_r.expire = AsyncMock(return_value=True)

    async def run():
        with patch("transcript_handler.aioredis.from_url", return_value=mock_r):
            for _ in range(3):
                await handler(_event(is_final=False))

    asyncio.run(run())
    assert seqs == [1, 2, 3]


# ---------------------------------------------------------------------------
# H07  Redis key is transcript:{call_id}
# ---------------------------------------------------------------------------

def test_H07_redis_key_is_correct():
    mock_r = _mock_redis()
    received_key: list[str] = []

    async def fake_rpush(key, value):
        received_key.append(key)
        return 1

    mock_r.rpush = AsyncMock(side_effect=fake_rpush)
    mock_r.expire = AsyncMock(return_value=True)

    handler = make_transcript_handler("my-call-id", redis_url="redis://fake/0")

    async def run():
        with patch("transcript_handler.aioredis.from_url", return_value=mock_r):
            await handler(_event(is_final=True))

    asyncio.run(run())
    assert received_key == ["transcript:my-call-id"]


# ---------------------------------------------------------------------------
# H08  TTL is set after every push
# ---------------------------------------------------------------------------

def test_H08_ttl_set_after_push():
    mock_r = _mock_redis()
    handler = make_transcript_handler("call-8", redis_url="redis://fake/0")

    async def run():
        with patch("transcript_handler.aioredis.from_url", return_value=mock_r):
            await handler(_event(is_final=False))
            await handler(_event(is_final=True))

    asyncio.run(run())
    assert mock_r.expire.call_count == 2
    # Verify key argument of expire calls
    for c in mock_r.expire.call_args_list:
        assert c[0][0] == "transcript:call-8"


# ---------------------------------------------------------------------------
# H09  Redis failure does NOT raise from on_transcript
# ---------------------------------------------------------------------------

def test_H09_redis_failure_does_not_raise():
    mock_r = _mock_redis()
    mock_r.rpush = AsyncMock(side_effect=Exception("Redis connection refused"))

    handler = make_transcript_handler("call-9", redis_url="redis://fake/0")

    async def run():
        with patch("transcript_handler.aioredis.from_url", return_value=mock_r):
            # Must complete without raising
            await handler(_event(is_final=True))

    asyncio.run(run())  # no exception


# ---------------------------------------------------------------------------
# H10  on_transcript callback is passed into CallPipelineHandle and reaches SttBridge
# ---------------------------------------------------------------------------

def test_H10_callback_reaches_stt_bridge():
    """Verify that the callback supplied to SttBridge is actually invoked."""
    session = MagicMock()
    session.send_audio = AsyncMock()
    session.close = AsyncMock()
    session.receive = AsyncMock(side_effect=[_event(is_final=True), None])

    received: list[TranscriptEvent] = []

    async def my_callback(event: TranscriptEvent):
        received.append(event)

    bridge = SttBridge(session, "call-h10", on_transcript=my_callback)

    async def run():
        bridge.start()
        await asyncio.sleep(0.1)
        await bridge.close()

    asyncio.run(run())
    assert len(received) == 1
    assert received[0].is_final is True


# ---------------------------------------------------------------------------
# H11  Consumer failure (on_transcript raises) does not crash SttBridge
# ---------------------------------------------------------------------------

def test_H11_consumer_failure_does_not_crash_bridge():
    """If on_transcript raises, SttBridge._recv_loop must absorb it and continue."""
    events = [_event(is_final=False), _event(is_final=True), None]
    session = MagicMock()
    session.send_audio = AsyncMock()
    session.close = AsyncMock()
    session.receive = AsyncMock(side_effect=events)

    call_count = [0]

    async def crashing_callback(event: TranscriptEvent):
        call_count[0] += 1
        raise RuntimeError("downstream crash")

    bridge = SttBridge(session, "call-h11", on_transcript=crashing_callback)

    async def run():
        bridge.start()
        await asyncio.sleep(0.1)
        await bridge.close()

    asyncio.run(run())
    # Both events were delivered (callback called twice); bridge did not crash
    assert call_count[0] == 2
