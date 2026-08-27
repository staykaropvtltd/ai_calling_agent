"""Phase 5 — unit tests for the STT/AI/TTS FrameProcessors (conversation.py).

Uses fake providers (matching the Protocol interfaces) and Pipecat's own
pipecat.tests.utils.run_test harness — tests the orchestration logic
(buffering, end-of-turn detection, session updates, frame flow) in
isolation, without needing the real Whisper model or a TTS engine loaded.
Real-provider behavior is covered separately in test_stt_tts_providers.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VG = str((Path(__file__).parent.parent / "services" / "voice-gateway").resolve())
if _VG not in sys.path:
    sys.path.insert(0, _VG)

from ai_provider import AIError  # noqa: E402
from conversation import AIProcessor, STTProcessor, TTSProcessor  # noqa: E402
from pipecat.frames.frames import (  # noqa: E402
    InputAudioRawFrame,
    OutputAudioRawFrame,
    TextFrame,
    TranscriptionFrame,
)
from pipecat.tests.utils import run_test  # noqa: E402
from stt_provider import WHISPER_SAMPLE_RATE, STTError  # noqa: E402
from tts_provider import TTSError  # noqa: E402

pytestmark = pytest.mark.asyncio


def _loud_audio_frame(n_samples: int = 320) -> InputAudioRawFrame:
    # int16 samples near full-scale -> RMS well above the 0.02 threshold.
    audio = (b"\xff\x7f" * n_samples)  # 32767 repeated, little-endian
    return InputAudioRawFrame(audio=audio, sample_rate=WHISPER_SAMPLE_RATE, num_channels=1)


def _silence_frame(n_samples: int = 320) -> InputAudioRawFrame:
    return InputAudioRawFrame(audio=b"\x00\x00" * n_samples, sample_rate=WHISPER_SAMPLE_RATE, num_channels=1)


class _FakeSTT:
    def __init__(self, text: str = "hello there", raise_error: bool = False):
        self.text = text
        self.raise_error = raise_error
        self.calls: list[bytes] = []

    async def transcribe(self, audio: bytes, sample_rate: int) -> str:
        self.calls.append(audio)
        if self.raise_error:
            raise STTError("simulated STT failure")
        return self.text


class _FakeAI:
    def __init__(self, response: str = "a response", raise_error: bool = False):
        self.response = response
        self.raise_error = raise_error
        self.seen_turns: list[list] = []

    async def generate_response(self, turns):
        self.seen_turns.append(list(turns))
        if self.raise_error:
            raise AIError("simulated AI failure")
        return self.response


class _FakeTTS:
    def __init__(self, raise_error: bool = False):
        self.raise_error = raise_error
        self.seen_text: list[str] = []

    async def synthesize(self, text: str):
        self.seen_text.append(text)
        if self.raise_error:
            raise TTSError("simulated TTS failure")
        return (b"\x01\x02" * 40, 8000)


class _FakeSessionStore:
    def __init__(self):
        self._sessions: dict[str, dict] = {}

    def get(self, call_id: str):
        return self._sessions.get(call_id)

    def add_turn(self, call_id: str, role: str, text: str) -> None:
        session = self._sessions.setdefault(call_id, {"turns": []})
        session["turns"].append({"role": role, "text": text})


# ── STTProcessor ─────────────────────────────────────────────────────────────


async def test_stt_processor_transcribes_after_silence_ends_turn():
    stt = _FakeSTT(text="hello there")
    proc = STTProcessor(stt, silence_frames_to_end_turn=3)

    frames = [_loud_audio_frame()] * 3 + [_silence_frame()] * 4
    down, _up = await run_test(
        proc,
        frames_to_send=frames,
        expected_down_frames=[TranscriptionFrame],
    )
    assert down[0].text == "hello there"
    assert len(stt.calls) == 1
    # buffered audio includes the loud frames (silence trailing is fine too)
    assert len(stt.calls[0]) > 0


async def test_stt_processor_ignores_pure_silence_no_speech_detected():
    stt = _FakeSTT()
    proc = STTProcessor(stt, silence_frames_to_end_turn=3)

    down, _up = await run_test(
        proc,
        frames_to_send=[_silence_frame()] * 5,
        expected_down_frames=[],
    )
    assert down == []
    assert stt.calls == []  # never even called — no speech was ever detected


async def test_stt_processor_failure_is_swallowed_not_propagated():
    stt = _FakeSTT(raise_error=True)
    proc = STTProcessor(stt, silence_frames_to_end_turn=2)

    frames = [_loud_audio_frame()] * 2 + [_silence_frame()] * 3
    down, _up = await run_test(proc, frames_to_send=frames, expected_down_frames=[])
    assert down == []  # STTError caught, no TranscriptionFrame, no crash


async def test_stt_processor_empty_transcript_produces_no_frame():
    stt = _FakeSTT(text="   ")  # whitespace-only -> treated as empty
    proc = STTProcessor(stt, silence_frames_to_end_turn=2)

    frames = [_loud_audio_frame()] * 2 + [_silence_frame()] * 3
    down, _up = await run_test(proc, frames_to_send=frames, expected_down_frames=[])
    assert down == []


async def test_stt_processor_flushes_on_max_buffer_even_without_silence():
    stt = _FakeSTT(text="long utterance")
    proc = STTProcessor(stt, max_buffer_seconds=0.05, silence_frames_to_end_turn=1000)

    # Just enough continuous "loud" frames to cross the tiny max-buffer
    # threshold exactly once (400 bytes/frame; threshold is 1600 bytes) —
    # more frames than this would trigger additional flushes, which is
    # correct processor behavior, just not what this test is isolating.
    frames = [_loud_audio_frame(n_samples=200)] * 4
    down, _up = await run_test(proc, frames_to_send=frames, expected_down_frames=[TranscriptionFrame])
    assert down[0].text == "long utterance"


# ── AIProcessor ──────────────────────────────────────────────────────────────


async def test_ai_processor_greets_on_start_frame():
    # run_test always sends its own StartFrame before frames_to_send, which
    # is exactly what triggers the greeting here — nothing extra needed.
    ai = _FakeAI(response="Hello, welcome.")
    store = _FakeSessionStore()
    proc = AIProcessor(ai, store, call_id="call-1")

    down, _up = await run_test(proc, frames_to_send=[], expected_down_frames=None)
    text_frames = [f for f in down if isinstance(f, TextFrame)]
    assert len(text_frames) == 1
    assert text_frames[0].text == "Hello, welcome."
    assert ai.seen_turns[0] == []  # greeting uses empty history


async def test_ai_processor_records_user_and_assistant_turns():
    # The processor also greets on run_test's automatic StartFrame first
    # (see test above) — this test's TranscriptionFrame produces a second,
    # separate TextFrame, which is what's asserted on here.
    ai = _FakeAI(response="an assistant reply")
    store = _FakeSessionStore()
    proc = AIProcessor(ai, store, call_id="call-2")

    down, _up = await run_test(
        proc,
        frames_to_send=[TranscriptionFrame(text="hi", user_id="caller", timestamp="t", finalized=True)],
        expected_down_frames=None,
    )
    text_frames = [f for f in down if isinstance(f, TextFrame)]
    assert len(text_frames) == 2  # greeting, then the reply to "hi"
    assert text_frames[-1].text == "an assistant reply"

    # The greeting itself is also recorded as an assistant turn (index 0),
    # so "hi" and its reply are indices 1 and 2.
    turns = store.get("call-2")["turns"]
    assert turns[-2] == {"role": "user", "text": "hi"}
    assert turns[-1] == {"role": "assistant", "text": "an assistant reply"}


async def test_ai_processor_failure_produces_safe_fallback_not_a_crash():
    ai = _FakeAI(raise_error=True)
    store = _FakeSessionStore()
    proc = AIProcessor(ai, store, call_id="call-3")

    down, _up = await run_test(
        proc,
        frames_to_send=[TranscriptionFrame(text="hi", user_id="caller", timestamp="t", finalized=True)],
        expected_down_frames=None,
    )
    text_frames = [f for f in down if isinstance(f, TextFrame)]
    # Both the auto-greeting and the reply to "hi" hit the same failing
    # provider, so both fall back — asserting on the last one (the reply).
    assert "sorry" in text_frames[-1].text.lower() or "wrong" in text_frames[-1].text.lower()


# ── TTSProcessor ─────────────────────────────────────────────────────────────


async def test_tts_processor_synthesizes_text_to_audio():
    tts = _FakeTTS()
    proc = TTSProcessor(tts)

    down, _up = await run_test(
        proc,
        frames_to_send=[TextFrame(text="hello world")],
        expected_down_frames=[OutputAudioRawFrame],
    )
    assert down[0].audio == b"\x01\x02" * 40
    assert tts.seen_text == ["hello world"]


async def test_tts_processor_skips_empty_text():
    tts = _FakeTTS()
    proc = TTSProcessor(tts)

    down, _up = await run_test(proc, frames_to_send=[TextFrame(text="   ")], expected_down_frames=[])
    assert down == []
    assert tts.seen_text == []


async def test_tts_processor_failure_is_swallowed_not_propagated():
    tts = _FakeTTS(raise_error=True)
    proc = TTSProcessor(tts)

    down, _up = await run_test(proc, frames_to_send=[TextFrame(text="hello")], expected_down_frames=[])
    assert down == []
