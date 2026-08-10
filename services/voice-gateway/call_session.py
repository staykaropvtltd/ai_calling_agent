from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class CallSession:
    """Runtime state for a single active voice call."""

    call_id: str
    tenant_id: str
    agent_id: str
    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    ended_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.ended_at is None

    def end(self) -> None:
        """Mark the call as ended."""
        if self.ended_at is None:
            self.ended_at = datetime.now(timezone.utc)


class CallSessionManager:
    """Manages the lifecycle of active call sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, CallSession] = {}

    def create(
        self,
        call_id: str,
        tenant_id: str,
        agent_id: str,
    ) -> CallSession:
        if call_id in self._sessions:
            raise ValueError(f"Call session already exists: {call_id}")

        session = CallSession(
            call_id=call_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
        )

        self._sessions[call_id] = session
        return session

    def get(self, call_id: str) -> CallSession | None:
        return self._sessions.get(call_id)

    def end(self, call_id: str) -> CallSession:
        session = self._sessions.get(call_id)

        if session is None:
            raise KeyError(f"Call session not found: {call_id}")

        session.end()
        return session

    def remove(self, call_id: str) -> CallSession | None:
        return self._sessions.pop(call_id, None)

    def active_count(self) -> int:
        return sum(
            session.is_active
            for session in self._sessions.values()
        )

    def clear(self) -> None:
        """End and remove all tracked sessions."""
        for session in self._sessions.values():
            session.end()

        self._sessions.clear()