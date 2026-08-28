"""Phase 5 — Speech-to-text provider abstraction.

Voice Gateway code must never call a specific STT vendor directly — it talks
to STTProvider, and any implementation (local or cloud) plugs in behind it.

No STT API credentials (e.g. DEEPGRAM_API_KEY, already wired into
docker-compose.yml but unused today) are available in this environment, so
the only implementation here is LocalWhisperSTTProvider: a genuine, fully
offline speech-to-text engine (faster-whisper / CTranslate2 Whisper) — not a
stub, not a fixture-matcher. It actually transcribes whatever audio it's
given. A cloud provider (Deepgram, per README's stated architecture) can be
added later as a second class implementing the same Protocol, with no
changes needed anywhere else.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

logger = logging.getLogger("staykaro.voice-gateway.stt")

# Whisper's native input rate. The pipeline's audio_in_sample_rate is set to
# match (see voice_pipeline.py) so audio arrives here already at this rate —
# no resampling needed in this module.
WHISPER_SAMPLE_RATE = 16000


class STTError(RuntimeError):
    """Typed, safe STT failure. Never wraps/exposes raw provider internals
    (stack traces, request bodies) — callers only see this message."""


class STTProvider(Protocol):
    async def transcribe(self, audio: bytes, sample_rate: int) -> str:
        """Return normalized text for the given PCM16 mono audio.

        Returns "" for empty/silent audio — never raises for that case, only
        for genuine provider failure (STTError).
        """
        ...


class LocalWhisperSTTProvider:
    """Offline STT via faster-whisper (CTranslate2 Whisper). No API key.

    English only ("tiny.en") — this project does not claim multilingual STT
    support; a real requirement for other languages would need a different
    model or a cloud provider with documented language coverage.

    The Whisper model weights are loaded lazily on the first transcribe() call
    (or eagerly via preload() at app startup). Construction is cheap so that
    importing this module never requires faster-whisper to be installed.
    """

    def __init__(
        self,
        model_size: str = "tiny.en",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model: object | None = None  # populated by _ensure_model()

    def preload(self) -> None:
        """Eagerly load the Whisper model — call once at application startup to
        pay the ~15-20s one-time cost before the first live call arrives."""
        self._ensure_model()

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise STTError("faster-whisper is not installed") from exc
        logger.info("Loading local Whisper model '%s' (one-time cost)...", self._model_size)
        self._model = WhisperModel(
            self._model_size, device=self._device, compute_type=self._compute_type
        )
        logger.info("Whisper model '%s' loaded", self._model_size)

    async def transcribe(self, audio: bytes, sample_rate: int) -> str:
        if not audio:
            return ""
        if sample_rate != WHISPER_SAMPLE_RATE:
            # Defensive: the pipeline is configured to deliver WHISPER_SAMPLE_RATE
            # already (see voice_pipeline.py), so this should never trigger in
            # practice — fail loudly rather than silently mis-transcribe.
            raise STTError(f"unexpected sample rate {sample_rate}, expected {WHISPER_SAMPLE_RATE}")
        # Reasonable upper bound so one pathological buffer can't hang a call
        # indefinitely — 30s of audio is already far beyond a normal IVR turn.
        max_bytes = 30 * WHISPER_SAMPLE_RATE * 2
        if len(audio) > max_bytes:
            audio = audio[:max_bytes]

        self._ensure_model()  # no-op on every call after the first

        def _run() -> str:
            import numpy as np

            samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
            segments, _info = self._model.transcribe(samples, language="en", vad_filter=False)  # type: ignore[union-attr]
            return " ".join(seg.text for seg in segments).strip()

        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, _run)
        except Exception as exc:
            # One failed transcription must not crash the call — the caller
            # (conversation.py) catches STTError and skips the turn.
            raise STTError("speech-to-text failed") from exc
