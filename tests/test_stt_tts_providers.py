"""Phase 5 — real-provider tests for LocalWhisperSTTProvider and
LocalPyttsx3TTSProvider.

These load the actual Whisper model / actual OS TTS engine — no mocks.
Following this repo's existing convention for a real-but-optional dependency
(see tests/test_tenant_isolation.py's real-Postgres skip pattern): skip
cleanly, not fail, when the local environment can't support them (no network
for the first Whisper model download, no TTS engine available on a bare CI
runner without espeak-ng installed) — CI has no path to guarantee either is
available. Both work today; both were run for real to write this file.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import numpy as np
import pytest

_VG = str((Path(__file__).parent.parent / "services" / "voice-gateway").resolve())
if _VG not in sys.path:
    sys.path.insert(0, _VG)

pytest.importorskip("faster_whisper", reason="faster-whisper not installed")
pytest.importorskip("pyttsx3", reason="pyttsx3 not installed")

from stt_provider import WHISPER_SAMPLE_RATE, LocalWhisperSTTProvider, STTError  # noqa: E402
from tts_provider import LocalPyttsx3TTSProvider, TTSError  # noqa: E402

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def tts():
    provider = LocalPyttsx3TTSProvider()
    return provider


@pytest.fixture(scope="module")
async def stt(tts):
    # Confirms a TTS engine is actually usable in this environment (not just
    # importable) before paying Whisper's ~15-20s model-load cost — if TTS
    # can't run here (e.g. no espeak-ng), skip the whole module cleanly.
    try:
        await tts.synthesize("probe")
    except TTSError as exc:
        pytest.skip(f"no working local TTS engine in this environment: {exc}")

    try:
        provider = LocalWhisperSTTProvider(model_size="tiny.en")
        provider.preload()  # model loading is now lazy; trigger it here to skip cleanly on failure
    except STTError as exc:
        pytest.skip(f"local Whisper model unavailable in this environment: {exc}")
    return provider


def _resample_to_whisper_rate(pcm16: bytes, src_rate: int) -> bytes:
    samples = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32)
    n_dst = int(len(samples) * WHISPER_SAMPLE_RATE / src_rate)
    resampled = np.interp(np.linspace(0, len(samples), n_dst), np.arange(len(samples)), samples)
    return resampled.astype(np.int16).tobytes()


# ── TTS ──────────────────────────────────────────────────────────────────────


async def test_tts_produces_real_nonempty_audio(tts):
    audio, sample_rate = await tts.synthesize("This is a real synthesis test.")
    assert isinstance(audio, bytes)
    assert len(audio) > 1000
    assert sample_rate > 0
    # Genuinely not silence: some samples must have real amplitude.
    samples = struct.unpack(f"<{len(audio)//2}h", audio)
    assert max(abs(s) for s in samples) > 500


async def test_tts_empty_text_raises():
    provider = LocalPyttsx3TTSProvider()
    with pytest.raises(TTSError):
        await provider.synthesize("")


async def test_tts_whitespace_only_raises():
    provider = LocalPyttsx3TTSProvider()
    with pytest.raises(TTSError):
        await provider.synthesize("   ")


async def test_tts_oversized_text_is_truncated_not_rejected(tts):
    long_text = "hello " * 500  # far beyond MAX_TEXT_CHARS
    audio, _sr = await tts.synthesize(long_text)
    assert len(audio) > 0  # truncated and synthesized, not an error


# ── STT ──────────────────────────────────────────────────────────────────────


async def test_stt_empty_audio_returns_empty_string(stt):
    text = await stt.transcribe(b"", WHISPER_SAMPLE_RATE)
    assert text == ""


async def test_stt_wrong_sample_rate_raises(stt):
    with pytest.raises(STTError):
        await stt.transcribe(b"\x00\x00" * 100, 8000)


async def test_stt_pure_silence_produces_empty_or_near_empty_text(stt):
    silence = b"\x00\x00" * WHISPER_SAMPLE_RATE  # 1 second of silence
    text = await stt.transcribe(silence, WHISPER_SAMPLE_RATE)
    assert text.strip() == "" or len(text) < 5  # Whisper sometimes emits noise tokens on silence


async def test_stt_real_round_trip_via_tts(tts, stt):
    """The end-to-end proof this pipeline is genuinely real: synthesize
    speech locally, feed the raw audio back into local STT, and get back
    text that actually matches — no fixtures, no fakes."""
    phrase = "The quick brown fox jumps over the lazy dog"
    audio, sample_rate = await tts.synthesize(phrase)
    resampled = _resample_to_whisper_rate(audio, sample_rate)

    transcript = await stt.transcribe(resampled, WHISPER_SAMPLE_RATE)

    # Real speech synthesis + real speech recognition on a moderately fast
    # local voice/model won't be byte-identical, but the actual words must
    # be recoverable.
    lowered = transcript.lower()
    assert "quick" in lowered or "fox" in lowered
    assert "dog" in lowered or "lazy" in lowered
