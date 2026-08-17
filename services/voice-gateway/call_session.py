from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.services.redis_service import (
    delete_call_session,
    get_call_session,
    save_call_session,
    update_call_session,
)


@dataclass
class CallSession:
    """Runtime state for a single active voice call."""

    call_id: str
    tenant_id: str
    agent_id: str
    started_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    ended_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.ended_at is None

    def end(self) -> None:
        """Mark the call as ended."""
        if self.ended_at is None:
            self.ended_at = datetime.now(UTC)


class CallSessionManager:
    """Manages call sessions in memory and in the NK-03 Redis session service."""

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

        existing = get_call_session(call_id)
        if existing is not None:
            raise ValueError(f"Call session already exists: {call_id}")

        session = CallSession(
            call_id=call_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
        )

        save_call_session(
            call_id,
            {
                "call_id": call_id,
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "started_at": session.started_at.isoformat(),
                "status": "active",
            },
        )

        self._sessions[call_id] = session
        return session

    def get(self, call_id: str) -> CallSession | None:
        session = self._sessions.get(call_id)

        if session is not None:
            return session

        redis_session = get_call_session(call_id)
        if redis_session is None:
            return None

        started_at = redis_session.get("started_at")
        parsed_started_at = (
            datetime.fromisoformat(started_at)
            if started_at
            else datetime.now(UTC)
        )

        return CallSession(
            call_id=redis_session["call_id"],
            tenant_id=redis_session["tenant_id"],
            agent_id=redis_session["agent_id"],
            started_at=parsed_started_at,
            metadata=redis_session.get("metadata", {}),
        )

    def end(self, call_id: str) -> CallSession:
        session = self._sessions.get(call_id)

        if session is None:
            session = self.get(call_id)

        if session is None:
            raise KeyError(f"Call session not found: {call_id}")

        session.end()

        update_call_session(call_id, "ended")

        return session

    def remove(self, call_id: str) -> CallSession | None:
        session = self._sessions.pop(call_id, None)

        delete_call_session(call_id)

        return session

    def active_count(self) -> int:
        return sum(
            session.is_active
            for session in self._sessions.values()
        )

    def clear(self) -> None:
        """End and remove all tracked sessions."""
        for call_id in list(self._sessions):
            try:
                self.end(call_id)
            finally:
                self.remove(call_id)
