"""Client for the internal calls API (services/api /internal/v1/calls)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

import httpx
from pydantic import BaseModel


class InternalApiError(RuntimeError):
    pass


class CallCreation(BaseModel):
    call_id: str
    tenant_id: str
    agent_id: str
    started_at: datetime


class CallFinalization(BaseModel):
    ended_at: datetime
    end_reason: str


class InternalCalls(Protocol):
    async def create(self, call: CallCreation) -> None: ...
    async def finalize(self, call_id: str, finalization: CallFinalization) -> None: ...


class InternalCallsClient:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client

    async def _post(self, path: str, payload: dict) -> None:
        try:
            if self._client is not None:
                response = await self._client.post(self._base_url + path, json=payload)
            else:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.post(self._base_url + path, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise InternalApiError(
                f"Internal calls API request failed with status {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise InternalApiError("Internal calls API request failed") from exc

    async def create(self, call: CallCreation) -> None:
        await self._post("/internal/v1/calls", call.model_dump(mode="json"))

    async def finalize(self, call_id: str, finalization: CallFinalization) -> None:
        await self._post(
            f"/internal/v1/calls/{call_id}/finalize",
            finalization.model_dump(mode="json"),
        )
