import uuid as _uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from src.database import Base


class Client(Base):
    """
    Represents a tenant/client organisation using the Staykaro platform.
    Maps to /admin/clients endpoints (NH-06).
    New columns (slug, plan, status, max_concurrent_calls, created_at, updated_at)
    are added with server-side defaults so existing rows in a live database
    remain valid after a schema refresh via create_all on a fresh deployment.
    """

    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    # slug: URL-safe unique identifier for the tenant. Nullable in DB so that
    # rows created before this column was added don't violate NOT NULL.
    slug = Column(String(100), unique=True, nullable=True, index=True)
    plan = Column(String(50), server_default="starter")  # starter | pro | enterprise
    status = Column(String(20), server_default="active")  # active | suspended | inactive
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    api_limit = Column(Integer, server_default="100")
    max_concurrent_calls = Column(Integer, server_default="10")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    users = relationship("User", back_populates="client")
    callers = relationship("Caller", back_populates="client")


class User(Base):
    """
    Admin/operator users managed through /admin/users (NH-06).
    Separate from the JWT credential used to call the API.
    """

    __tablename__ = "admin_users"

    id = Column(String(36), primary_key=True, default=lambda: str(_uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    role = Column(String(50), server_default="agent")  # super_admin | tenant_admin | agent
    tenant_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    status = Column(String(20), server_default="active")  # active | suspended
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    client = relationship("Client", back_populates="users")


class Caller(Base):
    """
    Inbound call requests persisted by the /call endpoint.
    client_id links a call to a Client for per-tenant stats (NH-06 stats endpoint).
    Nullable so calls created before this column existed remain valid.
    """

    __tablename__ = "call_requests"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String)
    phone_number = Column(String)
    hotel_name = Column(String)
    check_in_date = Column(String)
    check_out_date = Column(String)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    client = relationship("Client", back_populates="callers")


class Call(Base):
    """
    Authoritative record of a single voice call lifecycle, created by the voice
    gateway when a provider (Exotel etc.) reports the call as connected.
    call_id is a UUID assigned by the gateway; provider_call_id is the
    telephony provider's own identifier (e.g. Exotel CallSid).
    """

    __tablename__ = "calls"

    call_id = Column(String(36), primary_key=True)
    tenant_id = Column(String(255), nullable=False, index=True)
    agent_id = Column(String(255), nullable=False)
    provider_call_id = Column(String(255), nullable=True, index=True)
    status = Column(String(20), server_default="active")  # active | completed | failed
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    end_reason = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
