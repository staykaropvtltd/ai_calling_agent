"""Phase 5 — unit tests for LocalRuleBasedAIProvider.

Pure Python logic, no external dependency — always fast and reliable in CI,
matching this repo's convention of keeping the default suite dependency-free.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_VG = str((Path(__file__).parent.parent / "services" / "voice-gateway").resolve())
if _VG not in sys.path:
    sys.path.insert(0, _VG)

from ai_provider import LocalRuleBasedAIProvider  # noqa: E402

pytestmark = pytest.mark.asyncio


async def test_empty_history_returns_greeting():
    provider = LocalRuleBasedAIProvider()
    response = await provider.generate_response([])
    assert "hello" in response.lower() or "assistant" in response.lower()


async def test_confirmation_is_recognized():
    provider = LocalRuleBasedAIProvider()
    response = await provider.generate_response([{"role": "user", "text": "yes that's correct"}])
    assert "confirm" in response.lower() or "thank" in response.lower()


async def test_denial_is_recognized():
    provider = LocalRuleBasedAIProvider()
    response = await provider.generate_response([{"role": "user", "text": "no that's wrong"}])
    assert "no problem" in response.lower() or "change" in response.lower()


async def test_goodbye_is_recognized():
    provider = LocalRuleBasedAIProvider()
    response = await provider.generate_response([{"role": "user", "text": "okay, goodbye"}])
    assert "thank you" in response.lower() and "bye" in response.lower()


async def test_date_question_is_recognized():
    provider = LocalRuleBasedAIProvider()
    response = await provider.generate_response(
        [{"role": "user", "text": "what is my check in date"}]
    )
    assert "date" in response.lower()


async def test_human_handoff_request_is_recognized():
    provider = LocalRuleBasedAIProvider()
    response = await provider.generate_response(
        [{"role": "user", "text": "can I speak to a human agent"}]
    )
    assert "team" in response.lower() or "call you back" in response.lower()


async def test_unrecognized_input_falls_back_gracefully():
    provider = LocalRuleBasedAIProvider()
    response = await provider.generate_response(
        [{"role": "user", "text": "the quick brown fox jumps over something unrelated"}]
    )
    assert response  # never empty
    assert "sorry" in response.lower() or "again" in response.lower()


async def test_empty_user_text_falls_back_gracefully():
    provider = LocalRuleBasedAIProvider()
    response = await provider.generate_response([{"role": "user", "text": ""}])
    assert response


async def test_uses_most_recent_user_turn_not_earlier_ones():
    """Genuinely reads conversation state — a later turn overrides an
    earlier, contradictory one, proving the history is actually consulted."""
    provider = LocalRuleBasedAIProvider()
    turns = [
        {"role": "user", "text": "no that's wrong"},
        {"role": "assistant", "text": "No problem. Could you tell me more?"},
        {"role": "user", "text": "actually yes that's correct"},
    ]
    response = await provider.generate_response(turns)
    assert "confirm" in response.lower() or "thank" in response.lower()


async def test_response_never_exceeds_max_length():
    provider = LocalRuleBasedAIProvider()
    response = await provider.generate_response([{"role": "user", "text": "yes"}])
    assert len(response) <= 500
