from datetime import datetime

from sqlalchemy.orm import Session

from app.core.security import create_access_token, verify_password
from app.models.user import User


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    user = db.query(User).filter(User.email == email, User.is_active.is_(True)).first()

    if not user or not verify_password(password, user.hashed_password):
        return None

    return user


def login(db: Session, email: str, password: str) -> tuple[str, datetime] | None:
    user = authenticate_user(db, email, password)

    if not user:
        return None

    # tenant_id/role come from the stored user record, never from the
    # login request body — the client cannot choose its own tenant/role.
    return create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
    )
