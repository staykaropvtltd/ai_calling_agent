from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database.database import get_db
from app.schemas.auth import AuthenticatedUser, LoginRequest, TokenResponse
from app.services import auth_service

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["Auth"],
)


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    result = auth_service.login(db, request.email, request.password)

    if result is None:
        # Identical response for "no such user" and "wrong password" —
        # avoids leaking which one it was (user enumeration).
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    access_token, expires_at = result
    return TokenResponse(access_token=access_token, expires_at=expires_at)


@router.get("/me", response_model=AuthenticatedUser)
def me(current_user: AuthenticatedUser = Depends(get_current_user)):
    return current_user
