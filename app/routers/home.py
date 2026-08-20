import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import get_current_user
from app.database.database import get_db
from app.schemas.caller import CallerRequest
from app.services.bland_service import trigger_bland_call
from app.services.caller_service import save_call
from app.services.redis_service import get_call_session

router = APIRouter()


@router.get("/")
async def home() -> dict:
    return {"message": "Welcome to Staykaro AI Caller Backend!"}


@router.post("/call")
async def make_call(
    request: CallerRequest,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),  # JWT guard — token payload unused here
) -> dict:
    # Persist booking to Supabase PostgreSQL (async)
    await save_call(db, request)

    # trigger_bland_call uses the blocking `requests` library.
    # Run it in a thread pool to avoid blocking the async event loop.
    bland_response = await asyncio.to_thread(trigger_bland_call, request)

    call_id = bland_response.get("call_id")
    redis_session = get_call_session(call_id) if call_id else None

    if bland_response.get("status") == "error":
        return {
            "status": "failed",
            "database": "Saved",
            "bland": bland_response,
            "redis_session": redis_session,
        }

    return {
        "status": "success",
        "database": "Saved",
        "bland": bland_response,
        "redis_session": redis_session,
    }
