"""Phase 5 — Text-to-speech provider abstraction.

Same reasoning as stt_provider.py: no TTS API credentials are available, so
the only implementation is a genuine, fully offline engine (pyttsx3 — SAPI5
on Windows, espeak-ng on Linux/the deployed container), not a stub. A cloud
provider can be added later behind the same Protocol.
"""

from __future__ import annotations

import asyncio
import logging
import time
import wave
from io import BytesIO
from typing import Protocol

logger = logging.getLogger("staykaro.voice-gateway.tts")

# pyttsx3 output limits — a runaway/oversized response must not be spoken in
# full (unbounded provider latency, unbounded audio sent back to the caller).
MAX_TEXT_CHARS = 1000

# On Linux (espeak-ng driver), engine.runAndWait() can return before the WAV
# file it just wrote is actually flushed to disk — verified by direct
# reproduction (~30-70% of calls read back as a 0-frame/truncated WAV
# immediately after runAndWait() returns, 100% succeed within ~200ms of
# polling). Not a race in our code: the driver's own completion callback
# fires ahead of the OS-level file write completing. Poll briefly rather
# than trusting runAndWait()'s return as "file is ready".
_WAV_READY_POLL_TIMEOUT_SECONDS = 2.0
_WAV_READY_POLL_INTERVAL_SECONDS = 0.05


class TTSError(RuntimeError):
    """Typed, safe TTS failure. Never exposes raw provider internals."""


class TTSProvider(Protocol):
    async def synthesize(self, text: str) -> tuple[bytes, int]:
        """Return (pcm16_mono_audio_bytes, sample_rate) for the given text.

        Raises TTSError for empty text or a genuine provider failure.
        """
        ...


class LocalPyttsx3TTSProvider:
    """Offline TTS via pyttsx3 (OS-native voices — SAPI5/espeak-ng). No API key.

    pyttsx3's engine is not safe to share a single instance across concurrent
    calls (its event loop is synchronous and stateful), so this constructs a
    fresh engine per synthesize() call, run off the event loop in an
    executor. Slower than a persistent engine but correct under concurrency,
    which matters here since multiple calls can be active at once.
    """

    async def synthesize(self, text: str) -> tuple[bytes, int]:
        text = text.strip()
        if not text:
            raise TTSError("empty text")
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS]

        def _run() -> tuple[bytes, int]:
            import os
            import tempfile

            import pyttsx3

            engine = pyttsx3.init()
            try:
                fd, path = tempfile.mkstemp(suffix=".wav")
                os.close(fd)
                try:
                    engine.save_to_file(text, path)
                    engine.runAndWait()

                    deadline = time.monotonic() + _WAV_READY_POLL_TIMEOUT_SECONDS
                    last_exc: Exception | None = None
                    while True:
                        try:
                            with wave.open(path, "rb") as wav_file:
                                sample_rate = wav_file.getframerate()
                                channels = wav_file.getnchannels()
                                sampwidth = wav_file.getsampwidth()
                                raw = wav_file.readframes(wav_file.getnframes())
                            if raw:
                                break
                            last_exc = None  # valid header, just empty so far
                        except (EOFError, wave.Error) as exc:
                            last_exc = exc
                        if time.monotonic() >= deadline:
                            raise TTSError("TTS output file never became ready") from last_exc
                        time.sleep(_WAV_READY_POLL_INTERVAL_SECONDS)

                    if channels != 1 or sampwidth != 2:
                        raise TTSError(
                            f"unexpected TTS output format: channels={channels} "
                            f"sampwidth={sampwidth} (expected mono 16-bit)"
                        )
                    return raw, sample_rate
                finally:
                    os.unlink(path)
            finally:
                engine.stop()

        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, _run)
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError("text-to-speech failed") from exc


def wrap_wav(pcm16_mono: bytes, sample_rate: int) -> bytes:
    """Helper for tests/fixtures: wrap raw PCM16 mono in a WAV container."""
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16_mono)
    return buf.getvalue()
