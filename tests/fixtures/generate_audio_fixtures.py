"""Phase 5 — generates the deterministic test-audio fixtures under
tests/fixtures/audio/. Not run automatically (fixtures are checked in as
static files) — run manually only if the fixtures need regenerating:

    python tests/fixtures/generate_audio_fixtures.py

Uses pyttsx3 (the same local/offline engine used by
services/voice-gateway/tts_provider.py) to synthesize each phrase, then
resamples to 8000 Hz mono PCM16 — Exotel's documented Media Streams rate —
so these fixtures can be fed directly into the simulated telephony client
without any further conversion. Every phrase is written by this project for
this purpose; none are copyrighted or private recordings.
"""

from __future__ import annotations

import os
import struct
import wave
from pathlib import Path

FIXTURES = {
    "greeting_response.wav": "Hi, I have a question about my reservation.",
    "simple_question.wav": "Can you confirm my check in date?",
    "follow_up_question.wav": "And what time is check out on that day?",
    "goodbye.wav": "Okay that's all, thank you, goodbye.",
}

TARGET_SAMPLE_RATE = 8000
OUT_DIR = Path(__file__).parent / "audio"


def _resample_linear(samples: list[int], src_rate: int, dst_rate: int) -> list[int]:
    if src_rate == dst_rate or not samples:
        return samples
    n_dst = int(len(samples) * dst_rate / src_rate)
    out = []
    for i in range(n_dst):
        src_pos = i * src_rate / dst_rate
        lo = int(src_pos)
        hi = min(lo + 1, len(samples) - 1)
        frac = src_pos - lo
        out.append(int(samples[lo] * (1 - frac) + samples[hi] * frac))
    return out


def _generate_one(filename: str, text: str) -> None:
    import pyttsx3

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    engine = pyttsx3.init()
    tmp_path = str(OUT_DIR / f"_tmp_{filename}")
    try:
        engine.save_to_file(text, tmp_path)
        engine.runAndWait()
    finally:
        engine.stop()

    with wave.open(tmp_path, "rb") as w:
        src_rate = w.getframerate()
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, (
            f"unexpected format for {filename}: "
            f"channels={w.getnchannels()} sampwidth={w.getsampwidth()}"
        )
        raw = w.readframes(w.getnframes())

    samples = list(struct.unpack(f"<{len(raw) // 2}h", raw))
    resampled = _resample_linear(samples, src_rate, TARGET_SAMPLE_RATE)
    out_bytes = struct.pack(f"<{len(resampled)}h", *resampled)

    out_path = OUT_DIR / filename
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TARGET_SAMPLE_RATE)
        w.writeframes(out_bytes)

    os.remove(tmp_path)
    duration = len(resampled) / TARGET_SAMPLE_RATE
    print(f"wrote {out_path} ({duration:.2f}s, text={text!r})")


def main() -> None:
    import sys

    # A single pyttsx3 engine can leave Windows SAPI/COM in a bad state
    # across repeated init()/stop() cycles in one process, so this is
    # designed to be invoked once per fixture (see the loop in this
    # docstring's usage note) rather than looping in-process.
    if len(sys.argv) == 3:
        _generate_one(sys.argv[1], sys.argv[2])
    else:
        for filename, text in FIXTURES.items():
            _generate_one(filename, text)


if __name__ == "__main__":
    main()
