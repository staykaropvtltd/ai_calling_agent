"""HTTP client for services/api's internal job/event API (/internal/v1/events).

Mirrors services/voice-gateway/internal_calls.py's InternalCallsClient style
(same auth header, same error-wrapping convention) — kept as a separate,
minimal client rather than importing across service boundaries, since these
are independently deployable services.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx
from pydantic import BaseModel

_INTERNAL_API_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")


class JobsApiError(RuntimeError):
    """Raised for any failure talking to the internal jobs API. Never wraps
    raw response bodies — callers only see this message, so a transient
    HTTP failure can't leak internal details into worker logs."""


def _with_internal_auth(kwargs: dict) -> dict:
    if _INTERNAL_API_TOKEN:
        headers = dict(kwargs.get("headers") or {})
        headers["X-Internal-API-Token"] = _INTERNAL_API_TOKEN
        kwargs["headers"] = headers
    return kwargs


class Job(BaseModel):
    job_id: str
    tenant_id: Optional[str] = None
    call_id: Optional[str] = None
    provider_call_id: Optional[str] = None
    event_type: str
    payload: Optional[dict] = None
    status: str
    attempts: int
    max_attempts: int
    last_error: Optional[str] = None


class JobsClient:
    """Synchronous client — the worker is a plain blocking loop, not an
    asyncio application, so there is no event loop to make this async for.

    Pass client= to reuse one httpx.Client across calls (what the worker's
    main loop does — this class is called on every single iteration, so
    opening a fresh TCP connection per call would be wasteful) or to inject
    a test double (httpx.Client(transport=httpx.MockTransport(...))); when
    omitted, a short-lived client is opened per call, matching
    services/voice-gateway/internal_calls.py's async equivalent.
    """

    def __init__(
        self, base_url: str, client: httpx.Client | None = None, timeout: float = 10.0
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._timeout = timeout

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = self._base_url + path
        kwargs = _with_internal_auth(kwargs)
        try:
            if self._client is not None:
                return self._client.request(method, url, **kwargs)
            with httpx.Client(timeout=self._timeout) as client:
                return client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise JobsApiError(f"jobs API request failed: {method} {path}") from exc

    def health(self) -> bool:
        try:
            response = self._request("GET", "/health")
            return response.status_code == 200
        except JobsApiError:
            return False

    def list_eligible(self, statuses: list[str], limit: int = 20) -> list[Job]:
        response = self._request(
            "GET", "/internal/v1/events", params={"status": statuses, "limit": limit}
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise JobsApiError("list_eligible failed") from exc
        return [Job.model_validate(e) for e in response.json()["events"]]

    def claim(self, job_id: str) -> Job | None:
        """Returns None if the job could not be claimed (already claimed by
        another worker, already terminal, or not yet available) — never
        raises for that, only for a genuine transport/API failure."""
        response = self._request("POST", f"/internal/v1/events/{job_id}/claim")
        if response.status_code in (404, 409):
            return None
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise JobsApiError("claim failed") from exc
        return Job.model_validate(response.json())

    def complete(self, job_id: str) -> None:
        response = self._request("POST", f"/internal/v1/events/{job_id}/complete")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise JobsApiError("complete failed") from exc

    def fail(self, job_id: str, error: str, retry: bool = True) -> Job:
        response = self._request(
            "POST",
            f"/internal/v1/events/{job_id}/fail",
            json={"error": error, "retry": retry},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise JobsApiError("fail failed") from exc
        return Job.model_validate(response.json())

    def reap(self) -> list[str]:
        response = self._request("POST", "/internal/v1/events/reap")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise JobsApiError("reap failed") from exc
        return response.json()["reaped"]
