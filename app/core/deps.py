"""
Reusable FastAPI authentication dependency.

Any protected endpoint depends on `get_current_user` to obtain the
authenticated identity. Deliberately returns only identity (user_id,
tenant_id, role) with no authorization/permission logic — NK-06 (RBAC)
should build on top of this, e.g. `require_role("admin")` wrapping this
same dependency, rather than duplicating token handling.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import InvalidTokenError, decode_access_token
from app.schemas.auth import AuthenticatedUser

# auto_error=False so a missing header falls through to our own 401
# instead of FastAPI's default 403, keeping error handling consistent.
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> AuthenticatedUser:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None or not credentials.credentials:
        raise unauthorized

    try:
        payload = decode_access_token(credentials.credentials)
    except InvalidTokenError:
        # Same generic detail for every failure mode (expired, malformed,
        # bad signature, missing claims) — do not leak which check failed.
        raise unauthorized from None

    return AuthenticatedUser(
        user_id=payload["user_id"],
        tenant_id=payload["tenant_id"],
        role=payload["role"],
    )
