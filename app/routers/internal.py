from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/internal/v1/calls", tags=["Internal"])

class CallCreation(BaseModel):
    call_id: str
    tenant_id: str
    agent_id: str
    started_at: datetime

class CallFinalization(BaseModel):
    ended_at: datetime
    end_reason: str

@router.post("")
def create_call(call: CallCreation):
    return {"status": "ok"}

@router.post("/{call_id}/finalize")
def finalize_call(call_id: str, finalization: CallFinalization):
    return {"status": "ok"}
