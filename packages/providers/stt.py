"""Provider-neutral streaming STT contract for the voice gateway (SH-04)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol

from pydantic import BaseModel, Field


class SttError(RuntimeError):
    """A safe, typed failure returned by an STT provider."""


# ---------------------------------------------------------------------------
# Transcript events
# ---------------------------------------------------------------------------

class TranscriptEvent(BaseModel):
    """A single transcript emission from a streaming STT provider."""

    call_id: str = Field(min_length=1)
    transcript: str
    is_final: bool
    confidence: float = 0.0
    # Provider-specific raw event preserved for downstream consumers.
    # Never log this field — it may contain audio-derived text of sensitive calls.
    raw: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Provider settings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DeepgramSettings:
    """Configuration for the Deepgram streaming STT provider."""

    api_key: str
    model: str = "nova-2"
    language: str = "en"
    encoding: str = "linear16"
    sample_rate: int = 8000
    channels: int = 1
    interim_results: bool = True
    smart_format: bool = False
    connect_timeout_seconds: float = 10.0

    @classmethod
    def from_environment(cls) -> "DeepgramSettings":
        api_key = os.getenv("DEEPGRAM_API_KEY", "").strip()
        if not api_key:
            raise SttError("Missing required STT configuration: DEEPGRAM_API_KEY")
        return cls(
            api_key=api_key,
            model=os.getenv("DEEPGRAM_MODEL", "nova-2"),
            language=os.getenv("DEEPGRAM_LANGUAGE", "en"),
            encoding=os.getenv("DEEPGRAM_ENCODING", "linear16"),
            sample_rate=int(os.getenv("DEEPGRAM_SAMPLE_RATE", "8000")),
            channels=int(os.getenv("DEEPGRAM_CHANNELS", "1")),
            interim_results=os.getenv("DEEPGRAM_INTERIM_RESULTS", "true").lower() == "true",
            smart_format=os.getenv("DEEPGRAM_SMART_FORMAT", "false").lower() == "true",
            connect_timeout_seconds=float(os.getenv("DEEPGRAM_CONNECT_TIMEOUT_SECONDS", "10")),
        )


# ---------------------------------------------------------------------------
# Protocol / contract
# ---------------------------------------------------------------------------

class SttSession(Protocol):
    """A live STT session for one call.  Open → stream audio → iterate events → close."""

    async def send_audio(self, audio_bytes: bytes) -> None: ...
    async def receive(self) -> TranscriptEvent | None: ...
    async def close(self) -> None: ...


class SttProvider(Protocol):
    """Factory that opens a per-call streaming STT session."""

    async def open_session(self, call_id: str) -> SttSession: ...
