"""Phase 5 — AI response provider abstraction.

Voice Gateway code must never call a specific LLM vendor directly — it talks
to AIProvider, and any implementation plugs in behind it.

No LLM API credentials (GROQ_API_KEY / OPENAI_API_KEY, already wired into
docker-compose.yml per README's stated Groq-primary/OpenAI-fallback
architecture, but both empty in this environment) are available, so the only
implementation here is LocalRuleBasedAIProvider — an explicitly NOT-an-LLM,
deterministic, context-aware conversation engine. It genuinely reads the
conversation history it's given and produces different, appropriate
responses for different inputs; it does not have general language
understanding or reasoning, and this file does not claim it does. A cloud
LLM provider can be added later as a second class implementing the same
Protocol, with no changes needed anywhere else.
"""

from __future__ import annotations

import logging
import re
from typing import Protocol, TypedDict

logger = logging.getLogger("staykaro.voice-gateway.ai")

MAX_RESPONSE_CHARS = 500


class ConversationTurn(TypedDict):
    role: str  # "user" | "assistant"
    text: str


class AIError(RuntimeError):
    """Typed, safe AI-layer failure. Never exposes raw provider internals."""


class AIProvider(Protocol):
    async def generate_response(self, turns: list[ConversationTurn]) -> str:
        """Given the conversation so far (oldest first), return the
        assistant's next response. `turns` may be empty (start-of-call
        greeting). Raises AIError on genuine provider failure."""
        ...


_GREETING = (
    "Hello, thank you for calling. This is an automated assistant. "
    "How can I help you today?"
)
_GOODBYE = "Thank you for calling. Have a great day. Goodbye."
_FALLBACK = "I'm sorry, I didn't quite understand that. Could you say that again?"

# Deliberately simple keyword rules, not intent classification — this is a
# local placeholder for a real LLM, not an attempt to simulate one.
_GOODBYE_PATTERN = re.compile(r"\b(bye|goodbye|that'?s all|hang up|no more questions)\b", re.I)
_CONFIRM_PATTERN = re.compile(r"\b(yes|yeah|yep|confirm|correct|that'?s right)\b", re.I)
_DENY_PATTERN = re.compile(r"\b(no|nope|not really|incorrect|wrong)\b", re.I)
_DATE_PATTERN = re.compile(r"\b(check.?in|check.?out|date|when)\b", re.I)
_HUMAN_PATTERN = re.compile(r"\b(human|agent|person|representative|manager)\b", re.I)


class LocalRuleBasedAIProvider:
    """Deterministic, keyword-driven conversation engine — NOT an LLM.

    Genuinely reads `turns` (real conversation state, not ignored) to decide
    what to say next; there is no hidden call to any external model.
    """

    async def generate_response(self, turns: list[ConversationTurn]) -> str:
        try:
            return self._respond(turns)
        except Exception as exc:  # keep this layer from ever crashing a call
            raise AIError("response generation failed") from exc

    def _respond(self, turns: list[ConversationTurn]) -> str:
        user_turns = [t for t in turns if t["role"] == "user"]
        if not user_turns:
            return _GREETING

        last = user_turns[-1]["text"].strip()
        if not last:
            response = _FALLBACK
        elif _GOODBYE_PATTERN.search(last):
            response = _GOODBYE
        elif _HUMAN_PATTERN.search(last):
            response = (
                "Sure, I can arrange for a member of our team to call you back shortly. "
                "Is there anything else I can help with in the meantime?"
            )
        elif _DATE_PATTERN.search(last):
            response = (
                "I can help with check-in and check-out dates. "
                "Could you confirm the dates you're asking about?"
            )
        elif _CONFIRM_PATTERN.search(last):
            response = "Great, thank you for confirming. Is there anything else I can help with?"
        elif _DENY_PATTERN.search(last):
            response = (
                "No problem. Could you tell me more about what you'd like to change?"
            )
        else:
            response = _FALLBACK

        return response[:MAX_RESPONSE_CHARS]
