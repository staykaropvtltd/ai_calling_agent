from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.auth.jwt import create_access_token
from app.auth.schemas import TokenResponse
from app.config.settings import (
    API_PASSWORD,
    API_USERNAME,
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Obtain a Bearer token",
    description=(
        "OAuth2 password flow. "
        "Uses API_USERNAME / API_PASSWORD env vars until NK-05 user table is live."
    ),
)
async def login(form: OAuth2PasswordRequestForm = Depends()) -> TokenResponse:
    if not API_USERNAME or not API_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication not configured on this server",
        )

    if form.username != API_USERNAME or form.password != API_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return TokenResponse(
        access_token=create_access_token(form.username),
        expires_in=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
