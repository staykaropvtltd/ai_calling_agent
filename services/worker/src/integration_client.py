"""HTTP client for services/integration-service's internal processing contract.

Same auth/error-wrapping convention as jobs_client.py. The provider boundary
is deliberately this one HTTP call — swapping in a real external vendor
integration later means changing integration-service's implementation of
/internal/v1/process, not anything here or in the worker's main loop.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx
from pydantic import BaseModel

_INTERNAL_API_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")


class IntegrationError(RuntimeError):
    """Raised for any integration-service failure — transport error, or the
    service explicitly reporting it could not process the event. Treated by
    the worker as a retryable failure (see main.py::process_one)."""


class ProcessResult(BaseModel):
    status: str
    detail: Optional[str] = None


class IntegrationClient:
    """Pass client= to reuse one httpx.Client across calls (the worker's main
    loop calls process() on every iteration) or to inject a test double;
    otherwise a short-lived client is opened per call — same convention as
    JobsClient above."""

    def __init__(
        self, base_url: str, client: httpx.Client | None = None, timeout: float = 10.0
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._timeout = timeout

    def process(
        self,
        *,
        job_id: str,
        tenant_id: str | None,
        call_id: str | None,
        event_type: str,
        payload: dict | None,
    ) -> ProcessResult:
        headers = {}
        if _INTERNAL_API_TOKEN:
            headers["X-Internal-API-Token"] = _INTERNAL_API_TOKEN
        body = {
            "job_id": job_id,
            "tenant_id": tenant_id,
            "call_id": call_id,
            "event_type": event_type,
            "payload": payload,
        }
        try:
            if self._client is not None:
                response = self._client.post(
                    self._base_url + "/internal/v1/process", headers=headers, json=body
                )
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.post(
                        self._base_url + "/internal/v1/process", headers=headers, json=body
                    )
        except httpx.HTTPError as exc:
            raise IntegrationError("integration-service request failed") from exc

        if response.status_code >= 500:
            raise IntegrationError(
                f"integration-service returned {response.status_code}: transient failure"
            )
        if response.status_code >= 400:
            # A 4xx means the event itself is invalid — retrying it verbatim
            # would just fail the same way every time, but the decision of
            # whether that's worth a bounded retry vs. an immediate terminal
            # failure belongs to the caller (main.py), not this client.
            raise IntegrationError(
                f"integration-service rejected the event ({response.status_code}): {response.text[:500]}"
            )

        return ProcessResult.model_validate(response.json())
