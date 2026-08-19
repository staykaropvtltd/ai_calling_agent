from sqlalchemy import Boolean, Column, DateTime, Integer, String, func

from app.database.database import Base


class User(Base):
    """
    Minimal user record needed to authenticate and issue a JWT.

    tenant_id is a plain column (no FK to a tenants table) because tenant
    management itself is a separate ticket — this model only carries enough
    identity to support login and token issuance for NK-05.
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    tenant_id = Column(String, nullable=False, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False, default="agent")
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
