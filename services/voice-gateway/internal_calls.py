from __future__ import annotations
from datetime import datetime
from typing import Protocol
import httpx
from pydantic import BaseModel
class InternalApiError(RuntimeError): pass
class CallCreation(BaseModel):
    call_id: str; tenant_id: str; agent_id: str; started_at: datetime
class CallFinalization(BaseModel):
    ended_at: datetime; end_reason: str
class InternalCalls(Protocol):
    async def create(self, call: CallCreation) -> None: ...
    async def finalize(self, call_id: str, finalization: CallFinalization) -> None: ...
class InternalCallsClient:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None: self.base_url, self.client = base_url.rstrip('/'), client
    async def _post(self, path: str, payload: dict) -> None:
        try:
            if self.client: response = await self.client.post(self.base_url + path, json=payload)
            else:
                async with httpx.AsyncClient(timeout=10) as client: response = await client.post(self.base_url + path, json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc: raise InternalApiError('Internal calls API request failed') from exc
    async def create(self, call: CallCreation) -> None: await self._post('/internal/v1/calls', call.model_dump(mode='json'))
    async def finalize(self, call_id: str, finalization: CallFinalization) -> None: await self._post(f'/internal/v1/calls/{call_id}/finalize', finalization.model_dump(mode='json'))
