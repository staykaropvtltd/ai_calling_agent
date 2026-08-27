from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.core import security
from app.database.database import Base, get_db
from app.models.user import User
from main import app

# --- Isolated in-memory SQLite DB for auth tests, independent of the
# app's real Postgres engine (which is never contacted in these tests). ---
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_database():
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


def make_raw_token(payload: dict, secret: str = None, algorithm: str = None) -> str:
    """Build a token bypassing create_access_token, for negative-path tests."""
    return jwt.encode(
        payload,
        secret if secret is not None else settings.JWT_SECRET_KEY,
        algorithm=algorithm if algorithm is not None else settings.JWT_ALGORITHM,
    )


# ---------------------------------------------------------------------------
# app.core.security — token creation/decoding as pure functions
# ---------------------------------------------------------------------------


def test_create_access_token_contains_required_claims():
    token, expires_at = security.create_access_token(
        user_id=42, tenant_id="tenant-xyz", role="admin"
    )

    payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])

    assert payload["user_id"] == "42"
    assert payload["tenant_id"] == "tenant-xyz"
    assert payload["role"] == "admin"
    assert "exp" in payload
    assert isinstance(expires_at, datetime)


def test_decode_access_token_valid_round_trip():
    token, _ = security.create_access_token(user_id=1, tenant_id="t1", role="agent")

    payload = security.decode_access_token(token)

    assert payload["user_id"] == "1"
    assert payload["tenant_id"] == "t1"
    assert payload["role"] == "agent"


def test_decode_access_token_expired_rejected():
    expired_payload = {
        "user_id": "1",
        "tenant_id": "t1",
        "role": "agent",
        "exp": datetime.now(UTC) - timedelta(minutes=5),
    }
    token = make_raw_token(expired_payload)

    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(token)


def test_decode_access_token_invalid_signature_rejected():
    token, _ = security.create_access_token(user_id=1, tenant_id="t1", role="agent")
    header_b64, payload_b64, sig_b64 = token.split(".")

    # Flip the FIRST character of the signature, not the last character of
    # the whole token. A 32-byte HS256 signature's unpadded base64 encoding
    # ends in a partial 3-byte group, so the token's very last character
    # carries 2 "don't care" bits that pad out that final group rather than
    # encoding any real signature byte. Swapping token[-1] between 'A' (index
    # 0) and 'B' (index 1) only changes those padding bits — value-for-value
    # identical characters differ solely in bits base64 discards on decode —
    # so roughly 1 time in 16 (whenever the real last char is 'A'), the
    # "tampered" signature decodes to byte-identical bytes and verification
    # spuriously succeeds, making this test flaky rather than a real
    # tamper check (reproduced directly: token ending in 'A', flipped to
    # 'B', decoded to the exact same signature bytes via PyJWT). The first
    # signature character sits in a complete 3-byte group, so any
    # substitution there deterministically changes the decoded bytes.
    flipped_char = "A" if sig_b64[0] != "A" else "B"
    tampered = f"{header_b64}.{payload_b64}.{flipped_char}{sig_b64[1:]}"

    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(tampered)


def test_decode_access_token_wrong_secret_rejected():
    valid_payload = {
        "user_id": "1",
        "tenant_id": "t1",
        "role": "agent",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    token = make_raw_token(valid_payload, secret="a-completely-different-secret-value-32bytes")

    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(token)


def test_decode_access_token_malformed_rejected():
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token("this-is-not-a-jwt")


def test_decode_access_token_missing_required_claims_rejected():
    incomplete_payload = {
        "user_id": "1",
        # tenant_id and role deliberately omitted
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    token = make_raw_token(incomplete_payload)

    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(token)


# ---------------------------------------------------------------------------
# GET /api/v1/auth/me — protected endpoint via get_current_user dependency
# ---------------------------------------------------------------------------


def test_protected_endpoint_valid_token_returns_user_context():
    token, _ = security.create_access_token(user_id=7, tenant_id="tenant-7", role="agent")

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body == {"user_id": "7", "tenant_id": "tenant-7", "role": "agent"}


def test_protected_endpoint_missing_token_rejected():
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401


def test_protected_endpoint_malformed_token_rejected():
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401


def test_protected_endpoint_expired_token_rejected():
    expired_payload = {
        "user_id": "1",
        "tenant_id": "t1",
        "role": "agent",
        "exp": datetime.now(UTC) - timedelta(minutes=1),
    }
    token = make_raw_token(expired_payload)

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_protected_endpoint_invalid_signature_rejected():
    valid_payload = {
        "user_id": "1",
        "tenant_id": "t1",
        "role": "agent",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    token = make_raw_token(valid_payload, secret="a-different-wrong-secret-value-32b")

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_protected_endpoint_missing_claims_rejected():
    incomplete_payload = {
        "user_id": "1",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    token = make_raw_token(incomplete_payload)

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login
# ---------------------------------------------------------------------------


def test_login_success_returns_token_with_correct_claims():
    db = TestSessionLocal()
    db.add(
        User(
            tenant_id="tenant-1",
            email="jane@example.com",
            hashed_password=security.hash_password("Secr3tPass!"),
            role="agent",
        )
    )
    db.commit()
    db.close()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "jane@example.com", "password": "Secr3tPass!"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"

    decoded = security.decode_access_token(body["access_token"])
    assert decoded["tenant_id"] == "tenant-1"
    assert decoded["role"] == "agent"


def test_login_wrong_password_rejected():
    db = TestSessionLocal()
    db.add(
        User(
            tenant_id="tenant-1",
            email="wrongpass@example.com",
            hashed_password=security.hash_password("Secr3tPass!"),
            role="agent",
        )
    )
    db.commit()
    db.close()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "wrongpass@example.com", "password": "not-the-password"},
    )

    assert response.status_code == 401


def test_login_unknown_user_rejected():
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "whatever"},
    )

    assert response.status_code == 401
