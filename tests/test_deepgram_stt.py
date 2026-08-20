"""
Focused unit tests for SH-04: Deepgram streaming STT.

All tests are fully mocked ΓÇö no real network connections.

Coverage:
 T01  Missing DEEPGRAM_API_KEY raises SttError with the env var name
 T02  DeepgramSettings.from_environment() reads all config vars correctly
 T03  _build_url includes model, encoding, sample_rate, channels, interim_results
 T04  open_session passes Authorization header with Token (not URL); URL never contains key
 T05  open_session raises SttError on connection timeout
 T06  open_session raises SttError on WebSocket connection failure
 T07  send_audio forwards raw bytes to the WebSocket
 T08  send_audio raises SttError when the connection is closed
 T09  receive() returns None for non-Results Deepgram messages (metadata)
 T10  receive() returns interim TranscriptEvent (is_final=False)
 T11  receive() returns final TranscriptEvent (is_final=True) with confidence
 T12  receive() raises SttError on malformed (non-JSON) message
 T13  receive() raises SttError on ConnectionClosedError (provider failure)
 T14  receive() returns None on clean ConnectionClosedOK (normal shutdown)
 T15  close() sends CloseStream JSON before closing WebSocket
 T16  close() is idempotent (safe to call twice)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call as mock_call

import pytest
import websockets
import websockets.exceptions

# Make packages importable from workspace root
_ROOT = str(Path(__file__).parent.parent.resolve())
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from packages.providers.stt import DeepgramSettings, SttError, TranscriptEvent
from packages.providers.deepgram import (
    DeepgramSttProvider,
    DeepgramSttSession,
    _build_url,
    _parse_transcript,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(**overrides) -> DeepgramSettings:
    defaults = dict(
        api_key="dg-test-key",
        model="nova-2",
        language="en",
        encoding="linear16",
        sample_rate=8000,
        channels=1,
        interim_results=True,
        smart_format=False,
        connect_timeout_seconds=5.0,
    )
    defaults.update(overrides)
    return DeepgramSettings(**defaults)


def _mock_ws() -> MagicMock:
    ws = MagicMock()
    ws.send = AsyncMock()
    ws.recv = AsyncMock()
    ws.close = AsyncMock()
    return ws


def _results_message(transcript: str, is_final: bool, confidence: float = 0.9) -> str:
    return json.dumps({
        "type": "Results",
        "is_final": is_final,
        "channel": {
            "alternatives": [{"transcript": transcript, "confidence": confidence}]
        },
    })


def _metadata_message() -> str:
    return json.dumps({"type": "Metadata", "transaction_key": "abc"})


# ---------------------------------------------------------------------------
# T01  Missing DEEPGRAM_API_KEY
# ---------------------------------------------------------------------------

def test_T01_missing_api_key_raises_stt_error(monkeypatch):
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    with pytest.raises(SttError, match="DEEPGRAM_API_KEY"):
        DeepgramSettings.from_environment()


# ---------------------------------------------------------------------------
# T02  from_environment() reads all config vars
# ---------------------------------------------------------------------------

def test_T02_from_environment_reads_all_vars(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "key-abc")
    monkeypatch.setenv("DEEPGRAM_MODEL", "nova-3")
    monkeypatch.setenv("DEEPGRAM_LANGUAGE", "hi")
    monkeypatch.setenv("DEEPGRAM_ENCODING", "mulaw")
    monkeypatch.setenv("DEEPGRAM_SAMPLE_RATE", "16000")
    monkeypatch.setenv("DEEPGRAM_CHANNELS", "2")
    monkeypatch.setenv("DEEPGRAM_INTERIM_RESULTS", "false")
    monkeypatch.setenv("DEEPGRAM_SMART_FORMAT", "true")
    monkeypatch.setenv("DEEPGRAM_CONNECT_TIMEOUT_SECONDS", "7")

    s = DeepgramSettings.from_environment()
    assert s.api_key == "key-abc"
    assert s.model == "nova-3"
    assert s.language == "hi"
    assert s.encoding == "mulaw"
    assert s.sample_rate == 16000
    assert s.channels == 2
    assert s.interim_results is False
    assert s.smart_format is True
    assert s.connect_timeout_seconds == 7.0


# ---------------------------------------------------------------------------
# T03  _build_url includes all query params
# ---------------------------------------------------------------------------

def test_T03_build_url_contains_correct_params():
    s = _settings(model="nova-2", encoding="linear16", sample_rate=8000,
                  channels=1, interim_results=True, smart_format=False, language="en")
    url = _build_url(s)
    assert url.startswith("wss://api.deepgram.com/v1/listen?")
    assert "model=nova-2" in url
    assert "encoding=linear16" in url
    assert "sample_rate=8000" in url
    assert "channels=1" in url
    assert "interim_results=true" in url
    assert "smart_format=false" in url
    assert "language=en" in url
    # API key must NOT be in the URL
    assert "dg-test-key" not in url


# ---------------------------------------------------------------------------
# T04  open_session passes Authorization header; key not in URL
# ---------------------------------------------------------------------------

def test_T04_open_session_uses_auth_header_not_url():
    s = _settings()
    provider = DeepgramSttProvider(s)
    mock_ws = _mock_ws()

    captured_url = {}
    captured_headers = {}

    async def fake_connect(url, extra_headers=None, **kwargs):
        captured_url["url"] = url
        captured_headers["headers"] = dict(extra_headers or {})
        return mock_ws

    async def run():
        async def _passthrough(coro, timeout):
            return await coro

        with patch("packages.providers.deepgram.websockets.connect", side_effect=fake_connect):
            with patch("packages.providers.deepgram.asyncio.wait_for", side_effect=_passthrough):
                session = await provider.open_session("call-1")
        return session

    session = asyncio.run(run())
    assert isinstance(session, DeepgramSttSession)
    # API key must be in Authorization header
    assert captured_headers["headers"].get("Authorization") == "Token dg-test-key"
    # API key must NOT appear in the connection URL
    assert "dg-test-key" not in captured_url["url"]


# ---------------------------------------------------------------------------
# T05  open_session raises SttError on timeout
# ---------------------------------------------------------------------------

def test_T05_open_session_timeout_raises_stt_error():
    s = _settings()
    provider = DeepgramSttProvider(s)

    async def run():
        with patch("packages.providers.deepgram.asyncio.wait_for",
                   side_effect=asyncio.TimeoutError("slow")):
            with pytest.raises(SttError, match="timed out"):
                await provider.open_session("call-1")

    asyncio.run(run())


# ---------------------------------------------------------------------------
# T06  open_session raises SttError on WebSocket error
# ---------------------------------------------------------------------------

def test_T06_open_session_ws_error_raises_stt_error():
    s = _settings()
    provider = DeepgramSttProvider(s)

    async def run():
        with patch("packages.providers.deepgram.asyncio.wait_for",
                   side_effect=websockets.exceptions.WebSocketException("refused")):
            with pytest.raises(SttError, match="connection failed"):
                await provider.open_session("call-1")

    asyncio.run(run())


# ---------------------------------------------------------------------------
# T07  send_audio forwards bytes to ws.send
# ---------------------------------------------------------------------------

def test_T07_send_audio_forwards_bytes():
    ws = _mock_ws()
    session = DeepgramSttSession(ws, "call-2")
    audio = b"\x00\x01" * 80

    async def run():
        await session.send_audio(audio)

    asyncio.run(run())
    ws.send.assert_called_once_with(audio)


# ---------------------------------------------------------------------------
# T08  send_audio raises SttError when connection closed
# ---------------------------------------------------------------------------

def test_T08_send_audio_raises_stt_error_when_closed():
    ws = _mock_ws()
    ws.send = AsyncMock(
        side_effect=websockets.exceptions.ConnectionClosedError(None, None)
    )
    session = DeepgramSttSession(ws, "call-3")

    async def run():
        with pytest.raises(SttError, match="sending audio"):
            await session.send_audio(b"\x00" * 160)

    asyncio.run(run())


# ---------------------------------------------------------------------------
# T09  receive() returns None for non-Results messages
# ---------------------------------------------------------------------------

def test_T09_receive_returns_none_for_metadata():
    ws = _mock_ws()
    ws.recv = AsyncMock(return_value=_metadata_message())
    session = DeepgramSttSession(ws, "call-4")

    result = asyncio.run(session.receive())
    assert result is None


# ---------------------------------------------------------------------------
# T10  receive() returns interim TranscriptEvent
# ---------------------------------------------------------------------------

def test_T10_receive_returns_interim_transcript():
    ws = _mock_ws()
    ws.recv = AsyncMock(return_value=_results_message("hello", is_final=False, confidence=0.85))
    session = DeepgramSttSession(ws, "call-5")

    event = asyncio.run(session.receive())
    assert isinstance(event, TranscriptEvent)
    assert event.call_id == "call-5"
    assert event.transcript == "hello"
    assert event.is_final is False
    assert abs(event.confidence - 0.85) < 1e-6


# ---------------------------------------------------------------------------
# T11  receive() returns final TranscriptEvent
# ---------------------------------------------------------------------------

def test_T11_receive_returns_final_transcript():
    ws = _mock_ws()
    ws.recv = AsyncMock(return_value=_results_message("goodbye", is_final=True, confidence=0.99))
    session = DeepgramSttSession(ws, "call-6")

    event = asyncio.run(session.receive())
    assert event is not None
    assert event.transcript == "goodbye"
    assert event.is_final is True
    assert abs(event.confidence - 0.99) < 1e-6


# ---------------------------------------------------------------------------
# T12  receive() raises SttError on malformed (non-JSON) message
# ---------------------------------------------------------------------------

def test_T12_receive_raises_stt_error_on_malformed_message():
    ws = _mock_ws()
    ws.recv = AsyncMock(return_value="NOT JSON {{{{")
    session = DeepgramSttSession(ws, "call-7")

    async def run():
        with pytest.raises(SttError, match="non-JSON"):
            await session.receive()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# T13  receive() raises SttError on ConnectionClosedError (provider failure)
# ---------------------------------------------------------------------------

def test_T13_receive_raises_stt_error_on_provider_failure():
    ws = _mock_ws()
    ws.recv = AsyncMock(
        side_effect=websockets.exceptions.ConnectionClosedError(None, None)
    )
    session = DeepgramSttSession(ws, "call-8")

    async def run():
        with pytest.raises(SttError, match="error"):
            await session.receive()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# T14  receive() returns None on clean ConnectionClosedOK (normal shutdown)
# ---------------------------------------------------------------------------

def test_T14_receive_returns_none_on_clean_close():
    ws = _mock_ws()
    ws.recv = AsyncMock(
        side_effect=websockets.exceptions.ConnectionClosedOK(None, None)
    )
    session = DeepgramSttSession(ws, "call-9")

    result = asyncio.run(session.receive())
    assert result is None


# ---------------------------------------------------------------------------
# T15  close() sends CloseStream then closes socket
# ---------------------------------------------------------------------------

def test_T15_close_sends_closestream_and_closes():
    ws = _mock_ws()
    session = DeepgramSttSession(ws, "call-10")

    asyncio.run(session.close())

    # CloseStream must have been sent
    send_calls = ws.send.call_args_list
    assert len(send_calls) == 1
    sent_payload = json.loads(send_calls[0][0][0])
    assert sent_payload == {"type": "CloseStream"}
    ws.close.assert_called_once()


# ---------------------------------------------------------------------------
# T16  close() is idempotent
# ---------------------------------------------------------------------------

def test_T16_close_is_idempotent():
    ws = _mock_ws()
    session = DeepgramSttSession(ws, "call-11")

    asyncio.run(session.close())
    asyncio.run(session.close())  # second call must be a no-op

    assert ws.send.call_count == 1
    assert ws.close.call_count == 1
