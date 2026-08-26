import uuid as _uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from src.database import Base

# JSONB on PostgreSQL (binary, indexable); falls back to portable JSON on
# other dialects — needed because the test suite runs against in-memory
# SQLite (services/api/tests/conftest.py), which has no JSONB type.
_JSONB = JSONB().with_variant(JSON(), "sqlite")


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

    __table_args__ = (
        CheckConstraint("plan IN ('starter', 'pro', 'enterprise')", name="ck_clients_plan"),
        CheckConstraint(
            "status IN ('active', 'suspended', 'inactive')", name="ck_clients_status"
        ),
    )

    users = relationship("User", back_populates="client")
    callers = relationship("Caller", back_populates="client")


class User(Base):
    """
    Admin/operator users managed through /admin/users (NH-06).
    password_hash (bcrypt) backs real per-user login at /auth/login (NK-05) —
    the single shared API_PASSWORD credential is being phased out in favour
    of this table. Nullable so existing seed/service rows without a login
    (e.g. rows created before NK-05) remain valid.
    """

    __tablename__ = "admin_users"

    id = Column(String(36), primary_key=True, default=lambda: str(_uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=True)
    role = Column(String(50), server_default="agent")  # super_admin | tenant_admin | agent
    tenant_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    status = Column(String(20), server_default="active")  # active | suspended
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "role IN ('super_admin', 'tenant_admin', 'agent')", name="ck_admin_users_role"
        ),
        CheckConstraint("status IN ('active', 'suspended')", name="ck_admin_users_status"),
    )

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

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'completed', 'failed')", name="ck_calls_status"
        ),
        Index("idx_calls_tenant_started", "tenant_id", "started_at"),
    )

    turns = relationship(
        "CallTurn", back_populates="call", cascade="all, delete-orphan", order_by="CallTurn.started_at"
    )
    events = relationship("CallEvent", back_populates="call", cascade="all, delete-orphan")


class CallTurn(Base):
    """
    One row per conversational turn — one caller utterance or one agent
    response. Written by the voice gateway as SH-11 (turn management) lands;
    this is the durable side of what call_id + turn events produce.
    Database Design §3 (call_turns) · Owned by: Nishkala.
    """

    __tablename__ = "call_turns"

    turn_id = Column(String(36), primary_key=True, default=lambda: str(_uuid.uuid4()))
    call_id = Column(String(36), ForeignKey("calls.call_id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(String(255), nullable=False)
    speaker = Column(String(20), nullable=False)  # caller | agent
    language_code = Column(String(10), nullable=True)
    text = Column(Text, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("speaker IN ('caller', 'agent')", name="ck_call_turns_speaker"),
        Index("idx_call_turns_tenant_call", "tenant_id", "call_id"),
    )

    call = relationship("Call", back_populates="turns")


class CallEvent(Base):
    """
    One row per notable non-speech event during a call — barge-in, provider
    fallback, STT failure, etc. (SH-16 failure recovery, NH-07 live-call view).
    Database Design §3 (call_events) · Owned by: Nishkala.
    """

    __tablename__ = "call_events"

    event_id = Column(String(36), primary_key=True, default=lambda: str(_uuid.uuid4()))
    call_id = Column(String(36), ForeignKey("calls.call_id", ondelete="CASCADE"), nullable=False)
    tenant_id = Column(String(255), nullable=False)
    event_type = Column(String(50), nullable=False)  # barge_in | provider_fallback | stt_failure | ...
    payload = Column(_JSONB, nullable=True)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_call_events_tenant_call", "tenant_id", "call_id"),)

    call = relationship("Call", back_populates="events")


class AuditLog(Base):
    """
    One row per sensitive action — role changes, cross-tenant access attempts,
    admin actions on a client account (NK-16). Written by admin/internal
    routers whenever a mutating, security-relevant endpoint is hit.
    Database Design §5 (audit_logs) · Owned by: Nishkala.
    """

    __tablename__ = "audit_logs"

    audit_id = Column(String(36), primary_key=True, default=lambda: str(_uuid.uuid4()))
    tenant_id = Column(String(255), nullable=True)  # NULL for platform-level events
    user_id = Column(String(36), ForeignKey("admin_users.id"), nullable=True)
    action = Column(String(100), nullable=False)
    before_value = Column(_JSONB, nullable=True)
    after_value = Column(_JSONB, nullable=True)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_audit_logs_tenant_occurred", "tenant_id", "occurred_at"),)


class PhoneNumberRoute(Base):
    """
    Maps an Exotel virtual phone number (the 'Called' field in callbacks) to
    the tenant and agent that should handle calls on that number.
    number is the primary key — one number belongs to exactly one route.
    tenant_id stores str(Client.id), matching the representation used by Call.
    """

    __tablename__ = "phone_number_routes"

    number = Column(String(20), primary_key=True)
    tenant_id = Column(String(255), nullable=False)
    agent_id = Column(String(255), nullable=False)
    provider = Column(String(50), server_default="exotel")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
