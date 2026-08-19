"""
JWT and password-hashing primitives.

Kept free of FastAPI/DB imports so the token logic is trivially unit
testable and has a single, obvious place to change if the signing
algorithm or claim set ever needs to move (e.g. to asymmetric keys).
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

# Claims every access token must carry. Enforced manually after decode
# because PyJWT's `require` option only validates presence for a handful
# of registered claim names, not arbitrary custom ones like tenant_id/role.
REQUIRED_CLAIMS = ("user_id", "tenant_id", "role", "exp")


class InvalidTokenError(Exception):
    """
    Raised for any token validation failure (malformed, expired, bad
    signature, missing claims). Deliberately generic — the message is safe
    to log but callers must not echo library-internal detail to clients.
    """


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def create_access_token(*, user_id, tenant_id, role: str) -> tuple[str, datetime]:
    if not settings.JWT_SECRET_KEY:
        # Fail loudly rather than sign with an empty/None secret.
        raise RuntimeError("JWT_SECRET_KEY is not configured")

    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    payload = {
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "iat": now,
        "exp": expire,
    }

    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expire


def decode_access_token(token: str) -> dict:
    if not settings.JWT_SECRET_KEY:
        raise RuntimeError("JWT_SECRET_KEY is not configured")

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            # Explicit allowlist: the algorithm used to verify must never
            # be taken from the token itself (algorithm-confusion attacks,
            # e.g. a token claiming alg="none").
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.PyJWTError as exc:
        # Covers ExpiredSignatureError, InvalidSignatureError, DecodeError
        # (malformed), InvalidAlgorithmError, etc.
        raise InvalidTokenError("Token is invalid or expired") from exc

    missing = [claim for claim in REQUIRED_CLAIMS if claim not in payload]
    if missing:
        raise InvalidTokenError(f"Token missing required claims: {missing}")

    return payload
