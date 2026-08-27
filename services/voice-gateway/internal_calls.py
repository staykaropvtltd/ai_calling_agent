"""Client for the internal calls API (services/api /internal/v1/calls)."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Protocol

import httpx
from pydantic import BaseModel

# services/api's /internal/v1/* now requires this shared secret (see
# src/routers/internal.py::verify_internal_token) — must match INTERNAL_API_TOKEN
# on the api service exactly. Read directly from the environment rather than a
# shared config module since these are separate deployable services.
_INTERNAL_API_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")


class InternalApiError(RuntimeError):
    pass


def _with_internal_auth(kwargs: dict) -> dict:
    if _INTERNAL_API_TOKEN:
        headers = dict(kwargs.get("headers") or {})
        headers["X-Internal-API-Token"] = _INTERNAL_API_TOKEN
        kwargs["headers"] = headers
    return kwargs


class CallCreation(BaseModel):
    call_id: str
    tenant_id: str
    agent_id: str
    started_at: datetime
    provider_call_id: str | None = None


class CallFinalization(BaseModel):
    ended_at: datetime
    end_reason: str


class CallState(BaseModel):
    call_id: str
    tenant_id: str
    agent_id: str
    provider_call_id: str | None
    status: str
    started_at: datetime
    ended_at: datetime | None
    end_reason: str | None


class InternalCalls(Protocol):
    async def create(self, call: CallCreation) -> None: ...
    async def get(self, call_id: str) -> CallState | None: ...
    async def finalize(self, call_id: str, finalization: CallFinalization) -> None: ...


class InternalCallsClient:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = self._base_url + path
        kwargs = _with_internal_auth(kwargs)
        try:
            if self._client is not None:
                response = await self._client.request(method, url, **kwargs)
            else:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.request(method, url, **kwargs)
            return response
        except httpx.HTTPError as exc:
            raise InternalApiError("Internal calls API request failed") from exc

    async def create(self, call: CallCreation) -> None:
        response = await self._request(
            "POST", "/internal/v1/calls", json=call.model_dump(mode="json")
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise InternalApiError("Internal calls API request failed") from exc

    async def get(self, call_id: str) -> CallState | None:
        response = await self._request("GET", f"/internal/v1/calls/{call_id}")
        if response.status_code == 404:
            return None
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise InternalApiError("Internal calls API request failed") from exc
        return CallState.model_validate(response.json())

    async def finalize(self, call_id: str, finalization: CallFinalization) -> None:
        response = await self._request(
            "POST",
            f"/internal/v1/calls/{call_id}/finalize",
            json=finalization.model_dump(mode="json"),
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise InternalApiError("Internal calls API request failed") from exc


# ── Phone number routing ──────────────────────────────────────────────────────


class PhoneRoute(BaseModel):
    tenant_id: str
    agent_id: str
    provider: str


class InternalPhoneRoutingClient:
    """Resolves a dialed phone number to a (tenant_id, agent_id) pair via
    GET /internal/v1/phone-routes/{number}.  Follows the same HTTP/error
    conventions as InternalCallsClient."""

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = self._base_url + path
        kwargs = _with_internal_auth(kwargs)
        try:
            if self._client is not None:
                response = await self._client.request(method, url, **kwargs)
            else:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.request(method, url, **kwargs)
            return response
        except httpx.HTTPError as exc:
            raise InternalApiError("Internal phone routing API request failed") from exc

    async def resolve(self, dialed_number: str) -> tuple[str, str]:
        response = await self._request("GET", f"/internal/v1/phone-routes/{dialed_number}")
        if response.status_code == 404:
            raise InternalApiError("Phone number route not found")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise InternalApiError("Internal phone routing API request failed") from exc
        route = PhoneRoute.model_validate(response.json())
        return route.tenant_id, route.agent_id


# ── Phase 6: durable event/job recording ──────────────────────────────────────


class EventCreation(BaseModel):
    event_type: str
    provider_call_id: str | None = None
    tenant_id: str | None = None
    call_id: str | None = None
    payload: dict | None = None


class EventsClient:
    """Client for services/api's internal job/event API
    (/internal/v1/events) — the durable, restart-surviving idempotency
    guarantee exotel_routes.py uses in place of its old in-memory dedup set.
    Same auth/error-wrapping convention as InternalCallsClient above."""

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = self._base_url + path
        kwargs = _with_internal_auth(kwargs)
        try:
            if self._client is not None:
                response = await self._client.request(method, url, **kwargs)
            else:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.request(method, url, **kwargs)
            return response
        except httpx.HTTPError as exc:
            raise InternalApiError("Internal events API request failed") from exc

    async def record(
        self,
        *,
        provider_call_id: str,
        event_type: str,
        tenant_id: str | None = None,
        call_id: str | None = None,
        payload: dict | None = None,
    ) -> bool:
        """Durably records one event. Returns True if this is a genuine
        duplicate of a previously-recorded event (same provider_call_id +
        event_type) — callers must not repeat any side effect in that case.

        Keyword-argument signature (not a single EventCreation object) so
        this satisfies exotel_routes.py's EventRecorder Protocol exactly —
        the same calling convention as CallStore.set()/get() above.
        """
        event = EventCreation(
            provider_call_id=provider_call_id,
            event_type=event_type,
            tenant_id=tenant_id,
            call_id=call_id,
            payload=payload,
        )
        response = await self._request(
            "POST",
            "/internal/v1/events",
            json=event.model_dump(mode="json", exclude_none=True),
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise InternalApiError("Internal events API request failed") from exc
        return bool(response.json().get("duplicate", False))
