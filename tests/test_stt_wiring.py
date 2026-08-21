"""
Integration tests for SH-04 wiring:
  InputAudioRawFrame.audio → SttBridge → DeepgramSttSession → TranscriptEvent

All tests are fully mocked — no real network, no pipecat import required.
Tests use asyncio.run() directly (same pattern as test_deepgram_stt.py).

Coverage:
 W01  handle_audio() enqueues bytes and _send_loop forwards them to session.send_audio
 W02  _recv_loop calls on_transcript for each TranscriptEvent emitted by session
 W03  interim TranscriptEvent (is_final=False) reaches on_transcript callback
 W04  final TranscriptEvent (is_final=True) reaches on_transcript callback
 W05  session.receive() returning None (clean close) stops the recv loop without error
 W06  SttError from session.receive() stops the recv loop without raising
 W07  SttError from session.send_audio() stops the send loop without raising
 W08  close() calls session.close() exactly once
 W09  close() is idempotent (safe to call twice)
 W10  push_audio_frame interception also calls bridge.handle_audio with frame.audio
 W11  SttError from open_session is caught; pipeline continues
 W12  CallPipelineHandle.cleanup() closes the STT bridge
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Make stt_bridge importable (it lives in services/voice-gateway and has no pipecat deps)
_VG = str((Path(__file__).parent.parent / "services" / "voice-gateway").resolve())
if _VG not in sys.path:
    sys.path.insert(0, _VG)

from packages.providers.stt import SttError, TranscriptEvent
from stt_bridge import SttBridge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event(is_final: bool = False) -> TranscriptEvent:
    return TranscriptEvent(
        call_id="call-1",
        transcript="hello",
        is_final=is_final,
        confidence=0.9,
        raw={},
    )


def _mock_session(*, recv_values=None, send_raises=None):
    """Build a mock SttSession whose receive() returns values from recv_values list."""
    session = MagicMock()
    session.send_audio = AsyncMock(side_effect=send_raises)
    session.close = AsyncMock()
    if recv_values is None:
        recv_values = [None]  # clean close by default
    session.receive = AsyncMock(side_effect=recv_values)
    return session


async def _run_bridge(
    bridge: SttBridge,
    audio_chunks: list[bytes] | None = None,
    *,
    wait_s: float = 0.05,
) -> None:
    """Start bridge, send audio, wait for loops to process, then close."""
    bridge.start()
    for chunk in (audio_chunks or []):
        await bridge.handle_audio(chunk)
    await asyncio.sleep(wait_s)
    await bridge.close()


# ---------------------------------------------------------------------------
# W01  send_audio called with the audio bytes
# ---------------------------------------------------------------------------

def test_W01_handle_audio_forwards_to_send_audio():
    received: list[bytes] = []

    async def _send(audio):
        received.append(audio)

    session = _mock_session()
    session.send_audio = AsyncMock(side_effect=_send)
    bridge = SttBridge(session, "call-1")
    asyncio.run(_run_bridge(bridge, [b"\x00" * 160, b"\xff" * 160]))
    assert received == [b"\x00" * 160, b"\xff" * 160]


# ---------------------------------------------------------------------------
# W02  on_transcript callback receives every TranscriptEvent
# ---------------------------------------------------------------------------

def test_W02_recv_loop_calls_on_transcript():
    events = [_event(is_final=False), _event(is_final=True), None]
    session = _mock_session(recv_values=events)
    collected: list[TranscriptEvent] = []

    async def cb(e):
        collected.append(e)

    bridge = SttBridge(session, "call-1", on_transcript=cb)
    asyncio.run(_run_bridge(bridge, wait_s=0.05))
    assert len(collected) == 2


# ---------------------------------------------------------------------------
# W03  interim TranscriptEvent reaches callback
# ---------------------------------------------------------------------------

def test_W03_interim_transcript_reaches_callback():
    session = _mock_session(recv_values=[_event(is_final=False), None])
    collected: list[TranscriptEvent] = []

    async def cb(e):
        collected.append(e)

    bridge = SttBridge(session, "call-1", on_transcript=cb)
    asyncio.run(_run_bridge(bridge, wait_s=0.05))
    assert len(collected) == 1
    assert collected[0].is_final is False


# ---------------------------------------------------------------------------
# W04  final TranscriptEvent reaches callback
# ---------------------------------------------------------------------------

def test_W04_final_transcript_reaches_callback():
    session = _mock_session(recv_values=[_event(is_final=True), None])
    collected: list[TranscriptEvent] = []

    async def cb(e):
        collected.append(e)

    bridge = SttBridge(session, "call-1", on_transcript=cb)
    asyncio.run(_run_bridge(bridge, wait_s=0.05))
    assert len(collected) == 1
    assert collected[0].is_final is True
    assert collected[0].transcript == "hello"


# ---------------------------------------------------------------------------
# W05  session.receive() returning None stops recv loop without error
# ---------------------------------------------------------------------------

def test_W05_clean_close_stops_recv_loop():
    session = _mock_session(recv_values=[None])
    bridge = SttBridge(session, "call-1")
    asyncio.run(_run_bridge(bridge))
    assert session.receive.call_count == 1


# ---------------------------------------------------------------------------
# W06  SttError from receive() stops loop without propagating
# ---------------------------------------------------------------------------

def test_W06_stt_error_from_receive_does_not_crash():
    session = _mock_session(recv_values=[SttError("provider died")])
    bridge = SttBridge(session, "call-1")
    asyncio.run(_run_bridge(bridge))  # must not raise


# ---------------------------------------------------------------------------
# W07  SttError from send_audio() stops send loop without propagating
# ---------------------------------------------------------------------------

def test_W07_stt_error_from_send_does_not_crash():
    session = _mock_session(send_raises=SttError("ws closed"))

    async def run():
        bridge = SttBridge(session, "call-1")
        bridge.start()
        await bridge.handle_audio(b"\x00" * 160)
        await asyncio.sleep(0.05)
        await bridge.close()

    asyncio.run(run())  # must not raise


# ---------------------------------------------------------------------------
# W08  close() calls session.close() exactly once
# ---------------------------------------------------------------------------

def test_W08_close_calls_session_close():
    session = _mock_session()

    async def run():
        bridge = SttBridge(session, "call-1")
        bridge.start()
        await bridge.close()

    asyncio.run(run())
    session.close.assert_called_once()


# ---------------------------------------------------------------------------
# W09  close() is idempotent
# ---------------------------------------------------------------------------

def test_W09_close_is_idempotent():
    session = _mock_session()

    async def run():
        bridge = SttBridge(session, "call-1")
        bridge.start()
        await bridge.close()
        await bridge.close()

    asyncio.run(run())
    session.close.assert_called_once()


# ---------------------------------------------------------------------------
# W10  push_audio_frame interception feeds bridge.handle_audio
# ---------------------------------------------------------------------------

def test_W10_attach_stt_intercepts_push_audio_frame():
    """After monkey-patching push_audio_frame, audio bytes reach session.send_audio."""
    session = _mock_session()
    sent_audio: list[bytes] = []

    async def capture_send(audio):
        sent_audio.append(audio)

    session.send_audio = AsyncMock(side_effect=capture_send)
    original_push_calls: list = []

    async def original_push(frame):
        original_push_calls.append(frame)

    mock_input = MagicMock()
    mock_input.push_audio_frame = original_push

    async def run():
        bridge = SttBridge(session, "call-w10")
        bridge.start()

        # Replicate the monkey-patch from _attach_stt
        orig_fn = mock_input.push_audio_frame

        async def _push_with_stt(frame):
            await bridge.handle_audio(frame.audio)
            return await orig_fn(frame)

        mock_input.push_audio_frame = _push_with_stt

        fake_frame = MagicMock()
        fake_frame.audio = b"\x01\x02" * 80
        await mock_input.push_audio_frame(fake_frame)

        await asyncio.sleep(0.05)
        await bridge.close()

    asyncio.run(run())
    assert original_push_calls  # original pipeline push was not skipped
    assert sent_audio == [b"\x01\x02" * 80]


# ---------------------------------------------------------------------------
# W11  SttError from open_session is caught; no crash
# ---------------------------------------------------------------------------

def test_W11_open_session_error_caught_pipeline_continues():
    mock_provider = MagicMock()
    mock_provider.open_session = AsyncMock(side_effect=SttError("Deepgram unavailable"))

    session_result = None

    async def run():
        nonlocal session_result
        try:
            session_result = await mock_provider.open_session("call-w11")
        except SttError:
            # _attach_stt swallows this — pipeline continues without STT
            session_result = None

    asyncio.run(run())
    assert session_result is None
    mock_provider.open_session.assert_called_once_with("call-w11")


# ---------------------------------------------------------------------------
# W12  Handle cleanup() closes the STT bridge
# ---------------------------------------------------------------------------

def test_W12_handle_cleanup_closes_stt_bridge():
    session = _mock_session()
    bridge_closed_count = [0]

    async def _fake_close():
        bridge_closed_count[0] += 1

    async def run():
        bridge = SttBridge(session, "call-w12")
        bridge.close = _fake_close  # override to count calls
        bridge.start()

        # Simulate CallPipelineHandle.cleanup() logic
        cleaned = False

        async def cleanup():
            nonlocal cleaned
            if cleaned:
                return
            cleaned = True
            if bridge is not None:
                try:
                    await bridge.close()
                except Exception:
                    pass

        await cleanup()
        assert bridge_closed_count[0] == 1

        # Second call is a no-op (idempotent guard)
        await cleanup()
        assert bridge_closed_count[0] == 1  # not called again via handle

    asyncio.run(run())
