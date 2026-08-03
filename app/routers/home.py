from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.services.bland_service import trigger_bland_call
from app.schemas.caller import CallerRequest
from app.database.database import get_db
from app.services.caller_service import save_call

router = APIRouter()
@router.get("/")
def home():
    return {
        "message": "Welcome to Staykaro AI Caller Backend!"
    }

@router.post("/call")
def make_call(request: CallerRequest, db: Session = Depends(get_db)):
    save_call(db, request)

    bland_response = trigger_bland_call(request)

    if bland_response.get("status") == "error":
        return {
            "status": "failed",
            "database": "Saved",
            "bland": bland_response
        }

    return {
        "status": "success",
        "database": "Saved",
        "bland": bland_response
    }