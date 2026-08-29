from datetime import UTC, datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from src.config import (
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_ALGORITHM,
    JWT_REFRESH_TOKEN_EXPIRE_MINUTES,
    JWT_SECRET_KEY,
)

_bearer = HTTPBearer(auto_error=False)

# bcrypt caps input at 72 bytes; anything longer is silently truncated by the
# library itself, so no length validation is needed here beyond a sane cap
# against pathological input (enforced by Pydantic on UserCreate.password).


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed/legacy hash (e.g. empty string) — never a valid match.
        return False


# Permissions granted per role, returned by GET /auth/me.
_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "super_admin": ["tenant:read", "tenant:write", "user:read", "user:write", "call:read"],
    "tenant_admin": ["user:read", "call:read"],
    "agent": ["call:read"],
}


def create_access_token(
    subject: str,
    role: str = "user",
    client_id: Optional[int] = None,
    email: str = "",
    full_name: str = "",
) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict = {
        "sub": subject,
        "role": role,
        "exp": expire,
        "type": "access",
        "email": email,
        "full_name": full_name,
    }
    if client_id is not None:
        payload["client_id"] = client_id
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token(
    subject: str,
    role: str = "user",
    email: str = "",
    full_name: str = "",
) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=JWT_REFRESH_TOKEN_EXPIRE_MINUTES)
    payload: dict = {
        "sub": subject,
        "role": role,
        "exp": expire,
        "type": "refresh",
        "email": email,
        "full_name": full_name,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_refresh_token(token: str) -> dict:
    """Decode and validate a refresh token; raises HTTP 401 on any failure."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is not a refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    # Refuse refresh tokens presented as access tokens.
    if payload.get("type") == "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token cannot be used as an access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload
