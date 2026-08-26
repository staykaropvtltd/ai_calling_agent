"""Exotel HTTP boundary; no Exotel details leak into the Pipecat pipeline."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Protocol
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request, status
from internal_calls import CallCreation, CallFinalization, InternalApiError, InternalCalls
from pydantic import BaseModel, Field, ValidationError, model_validator

if TYPE_CHECKING:
    from packages.providers.telephony import ExotelSettings


class PhoneRouting(Protocol):
    async def resolve(self, dialed_number: str) -> tuple[str, str]: ...


class CallStore(Protocol):
    """Persistent mapping from Exotel provider_call_id to internal call_id.

    Implementations must survive gateway restarts so that end events (completed /
    failed / disconnected) arriving after a process restart can still be matched
    to their internal call record and finalized correctly.
    """

    def set(self, provider_call_id: str, call_id: str) -> None: ...
    def get(self, provider_call_id: str) -> str | None: ...
    def delete(self, provider_call_id: str) -> None: ...


class _DictCallStore:
    """In-memory fallback CallStore used when no external store is provided.

    Not restart-safe: the mapping is lost when the process exits.  Used as the
    default so that existing code and tests that don't supply a call_store
    continue to work without modification.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, provider_call_id: str, call_id: str) -> None:
        self._store[provider_call_id] = call_id

    def get(self, provider_call_id: str) -> str | None:
        return self._store.get(provider_call_id)

    def delete(self, provider_call_id: str) -> None:
        self._store.pop(provider_call_id, None)


class ExotelCallback(BaseModel):
    provider_call_id: str = Field(min_length=1)
    event: str = Field(min_length=1)
    dialed_number: str | None = None

    @model_validator(mode="before")
    @classmethod
    def translate_exotel_fields(cls, value: object) -> object:
        if isinstance(value, dict):
            return {
                "provider_call_id": value.get("CallSid"),
                "event": value.get("EventType"),
                "dialed_number": value.get("Called"),
            }
        return value


def build_exotel_router(
    session_manager: object,
    settings: ExotelSettings,
    calls: InternalCalls,
    routing: PhoneRouting | None = None,
    call_store: CallStore | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/telephony/exotel", tags=["Exotel"])
    handled_events: set[tuple[str, str]] = set()
    _store: CallStore = call_store if call_store is not None else _DictCallStore()

    @router.post("/callback")
    async def callback(
        request: Request,
        x_exotel_webhook_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, str]:
        if not x_exotel_webhook_token or not hmac.compare_digest(
            x_exotel_webhook_token, settings.webhook_token
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid Exotel callback authentication",
            )

        content_type = request.headers.get("content-type", "")
        try:
            if "application/x-www-form-urlencoded" in content_type:
                form = await request.form()
                raw: dict = dict(form)
            else:
                raw = await request.json()
            payload = ExotelCallback.model_validate(raw)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid request body",
            ) from exc

        key = (payload.provider_call_id, payload.event.lower())
        if key in handled_events:
            return {
                "status": "duplicate",
                "call_id": _store.get(payload.provider_call_id) or "",
            }
        handled_events.add(key)

        if payload.event.lower() in {"connected", "start", "answered", "started"}:
            if routing is None:
                raise HTTPException(
                    status_code=503,
                    detail="phone-number routing API dependency is unavailable",
                )
            if not payload.dialed_number:
                raise HTTPException(
                    status_code=422,
                    detail="Exotel callback is missing dialed number",
                )
            try:
                tenant_id, agent_id = await routing.resolve(payload.dialed_number)
            except InternalApiError as exc:
                raise HTTPException(status_code=404, detail="phone-number route not found") from exc

            call_id = str(uuid4())
            try:
                await calls.create(
                    CallCreation(
                        call_id=call_id,
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        started_at=datetime.now(UTC),
                        provider_call_id=payload.provider_call_id,
                    )
                )
            except InternalApiError as exc:
                raise HTTPException(
                    status_code=503, detail="internal call creation unavailable"
                ) from exc

            session_manager.create(call_id, tenant_id, agent_id)
            _store.set(payload.provider_call_id, call_id)
            return {"status": "session_started", "call_id": call_id}

        if payload.event.lower() in {"completed", "failed", "disconnected"}:
            call_id = _store.get(payload.provider_call_id)
            if not call_id:
                return {"status": "ignored", "call_id": ""}
            end_reason = (
                "provider_failure" if payload.event.lower() == "failed" else "caller_hangup"
            )
            try:
                await calls.finalize(
                    call_id,
                    CallFinalization(
                        ended_at=datetime.now(UTC),
                        end_reason=end_reason,
                    ),
                )
            except InternalApiError as exc:
                raise HTTPException(
                    status_code=503, detail="internal call finalization unavailable"
                ) from exc

            session = session_manager.get(call_id)
            if session is not None:
                session_manager.end(call_id)
                session_manager.remove(call_id)
            # Delete only after successful finalization — if finalize() raised above,
            # the mapping is preserved so the end event can be retried.
            _store.delete(payload.provider_call_id)
            return {"status": "session_cleaned", "call_id": call_id}

        return {"status": "ignored", "call_id": ""}

    return router
