from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.schemas.caller import CallerRequest
from app.database.database import get_db

from app.services.caller_service import save_call
from app.services.bland_service import trigger_bland_call
from app.services.redis_service import get_call_session

router = APIRouter()


@router.get("/")
def home():
    return {
        "message": "Welcome to Staykaro AI Caller Backend!"
    }


@router.post("/call")
def make_call(request: CallerRequest, db: Session = Depends(get_db)):

    # Save booking in PostgreSQL
    save_call(db, request)

    # Trigger Bland AI call
    bland_response = trigger_bland_call(request)

    # Get call_id returned by Bland
    call_id = bland_response.get("call_id")

    # Read session from Redis
    redis_session = None
    if call_id:
        redis_session = get_call_session(call_id)

    if bland_response.get("status") == "error":
        return {
            "status": "failed",
            "database": "Saved",
            "bland": bland_response,
            "redis_session": redis_session
        }

    return {
        "status": "success",
        "database": "Saved",
        "bland": bland_response,
        "redis_session": redis_session
    }