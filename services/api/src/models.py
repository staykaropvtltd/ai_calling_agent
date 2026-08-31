import uuid as _uuid

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
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
    """

    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=True, index=True)
    plan = Column(String(50), server_default="starter")  # starter | pro | enterprise
    status = Column(String(20), server_default="active")  # active | suspended | inactive
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    api_limit = Column(Integer, server_default="100")
    max_concurrent_calls = Column(Integer, server_default="10")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # Internationalisation fields (migration a1b2c3d4e5f6). Nullable so
    # existing rows remain valid; defaults applied in the client router.
    country = Column(String(2), nullable=True)  # ISO 3166-1 α-2: "AE", "IN", "US"
    timezone = Column(String(100), nullable=True)  # IANA: "Asia/Dubai", "Asia/Kolkata"
    currency = Column(String(3), nullable=True)  # ISO 4217: "AED", "INR", "USD"
    default_language = Column(String(10), nullable=True)  # BCP 47: "en", "ar", "hi"
    phone_country_code = Column(String(5), nullable=True)  # "+971", "+91", "+1"

    __table_args__ = (
        CheckConstraint("plan IN ('starter', 'pro', 'enterprise')", name="ck_clients_plan"),
        CheckConstraint("status IN ('active', 'suspended', 'inactive')", name="ck_clients_status"),
    )

    users = relationship("User", back_populates="client")
    callers = relationship("Caller", back_populates="client")
    customers = relationship("Customer", back_populates="client")


class User(Base):
    """
    Admin/operator users managed through /admin/users (NH-06).
    password_hash (bcrypt) backs real per-user login at /auth/login (NK-05).
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


class Customer(Base):
    """
    A deduplicated contact/customer record scoped to a single tenant.
    Introduced in Phase 1 (migration c3d4e5f6a7b8) to give call records,
    campaigns, and conversation history a stable entity to attach to — rather
    than embedding customer fields inline on every call_request row.

    phone is stored in E.164 format (+CCNNNNN). The combination
    (client_id, phone) is unique: within a tenant the same phone number always
    resolves to the same customer, allowing safe upsert behaviour.

    client_id mirrors the call_requests pattern (Integer FK to clients.id,
    cast to text for the RLS tenant_isolation policy).
    """

    __tablename__ = "customers"

    id = Column(String(36), primary_key=True, default=lambda: str(_uuid.uuid4()))
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=False)  # E.164: "+971501234567"
    email = Column(String(255), nullable=True)
    language_code = Column(String(10), nullable=True)  # BCP 47: "en", "ar", "hi"
    timezone = Column(String(100), nullable=True)  # IANA timezone
    country_code = Column(String(2), nullable=True)  # ISO 3166-1 α-2
    notes = Column(Text, nullable=True)
    external_id = Column(String(255), nullable=True)  # opaque CRM / PMS reference
    metadata_json = Column(_JSONB, nullable=True)  # arbitrary extra fields (JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # Unique phone per tenant — basis for safe upsert
        Index("uq_customers_client_phone", "client_id", "phone", unique=True),
        Index("idx_customers_client_id", "client_id"),
    )

    client = relationship("Client", back_populates="customers")
    call_requests = relationship("Caller", back_populates="customer")


class Caller(Base):
    """
    Represents a call work-item: either a single outbound call request (POST
    /call) or a row imported from a campaign contact list.

    Phase 1 additions (migration c3d4e5f6a7b8):
      status           — the call's lifecycle state (see CALL_REQUEST_STATUSES)
      call_type        — outbound | inbound
      is_simulation    — True when processed by a local dev/test provider, not
                         a real telephony carrier. A simulated call MUST NEVER
                         be presented to the client as a real completed call.
      customer_id      — FK to customers.id, populated by the dialler or manually
      telephony_call_id — logical reference to the calls.call_id created by the
                         voice gateway when this work-item is actually dialled.
                         Not a DB FK (avoids requiring the voice session to exist
                         before the work-item is created); enforced by the dialler.
      connection_status — whether the call was attempted and whether the remote
                         party picked up (independent of the conversation outcome).
      failure_reason   — machine-readable cause when connection_status is
                         'failed_pre_connect', or when no_answer / voicemail.
      duration_seconds — wall-clock seconds of the connected conversation.
      recording_url    — storage URL for the call recording, if captured.
      notes            — free-form operator notes attached after the call.
      outcome          — human-readable result of the completed conversation.
    """

    __tablename__ = "call_requests"

    id = Column(Integer, primary_key=True, index=True)
    # Legacy fields — kept as-is for backward compatibility with existing rows
    customer_name = Column(String)
    phone_number = Column(String)
    hotel_name = Column(String)
    check_in_date = Column(String)
    check_out_date = Column(String)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # ── Phase 1 fields ─────────────────────────────────────────────────────────

    # Call lifecycle status. server_default='pending' so existing rows
    # that pre-date this column get the truthful "we don't know what
    # happened to this" state rather than a falsely-positive terminal state.
    status = Column(String(30), nullable=False, server_default="pending")

    call_type = Column(String(20), nullable=False, server_default="outbound")

    # False = processed by a real telephony carrier (Exotel, Twilio, etc.).
    # True  = processed by a local dev/test simulation — MUST NOT appear as
    #         a real call in any client-facing report or analytics.
    is_simulation = Column(Boolean, nullable=False, server_default="0")

    # FK to customers.id — populated by the dialler or during import.
    # Nullable: legacy rows and rows created without phone-to-customer
    # resolution have no customer linked yet.
    customer_id = Column(String(36), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)

    # Logical reference to the voice-gateway Call record for this work-item.
    # Not a DB FK because the Call row may not exist at import/queue time.
    # Populated by the dialler once the call is initiated.
    telephony_call_id = Column(String(36), nullable=True)

    # Whether the dial attempt reached a connected state.
    # not_attempted: never dialled (pending/cancelled/invalid number pre-dial)
    # attempted:     dialled but no answer / went to voicemail
    # connected:     remote party answered and conversation began
    # failed_pre_connect: technical failure before ring (provider error, etc.)
    connection_status = Column(String(30), nullable=False, server_default="not_attempted")

    # Machine-readable failure reason. NULL when connection_status='connected'.
    # Values: invalid_number | no_answer | voicemail | network_error |
    #         provider_error | cancelled | unknown
    failure_reason = Column(String(50), nullable=True)

    duration_seconds = Column(Integer, nullable=True)
    recording_url = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    # Conversation outcome — set after the call completes.
    # Values: completed_natural | caller_hangup | agent_finished | no_answer |
    #         voicemail | escalated | failed | cancelled
    outcome = Column(String(50), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'pending', 'queued', 'dialing', 'ringing', 'connected', "
            "'in_progress', 'completed', 'failed', 'cancelled', "
            "'no_answer', 'voicemail')",
            name="ck_call_requests_status",
        ),
        CheckConstraint(
            "call_type IN ('inbound', 'outbound')",
            name="ck_call_requests_call_type",
        ),
        CheckConstraint(
            "connection_status IN "
            "('not_attempted', 'attempted', 'connected', 'failed_pre_connect')",
            name="ck_call_requests_connection_status",
        ),
    )

    client = relationship("Client", back_populates="callers")
    customer = relationship(
        "Customer",
        back_populates="call_requests",
        foreign_keys=[customer_id],
    )


class Call(Base):
    """
    Authoritative record of a single voice-telephony session, created by the
    voice gateway when a provider (Exotel, Twilio, etc.) reports a call.
    call_id is a UUID assigned by the gateway; provider_call_id is the
    provider's own identifier (e.g. Exotel CallSid).

    Phase 1 additions (migration c3d4e5f6a7b8):
      is_simulation    — True when the call was handled by a local dev/test
                         pipeline (Whisper + rule-based + pyttsx3) rather than
                         a real carrier. MUST be passed by the voice gateway on
                         creation and MUST NOT be overridden by the finalize step.
      connection_status — whether the remote party answered.
                         server_default='connected': all pre-Phase-1 rows were
                         created by the gateway only when an inbound call was
                         already live, so they were all connected.
      call_request_id  — optional back-reference to the call_requests row that
                         originated this telephony session (for outbound calls
                         dispatched by the dialler). NULL for inbound calls and
                         for pre-Phase-1 rows.

    Status values (extended in Phase 1):
      active     — call in progress
      completed  — conversation finished normally (both parties present)
      failed     — technical failure prevented or ended the call
      no_answer  — call was placed but remote party did not answer
      voicemail  — call reached voicemail (not a live conversation)
      cancelled  — call was cancelled before it was initiated
    """

    __tablename__ = "calls"

    call_id = Column(String(36), primary_key=True)
    tenant_id = Column(String(255), nullable=False, index=True)
    agent_id = Column(String(255), nullable=False)
    provider_call_id = Column(String(255), nullable=True, index=True)
    status = Column(String(20), server_default="active")
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    end_reason = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # ── Phase 1 fields ─────────────────────────────────────────────────────────

    # False = real carrier; True = local simulation. Passed at creation time
    # by the voice gateway; never altered by finalize.
    is_simulation = Column(Boolean, nullable=False, server_default="0")

    # Whether the remote party answered. Pre-Phase-1 rows are all 'connected'
    # (gateway only created Call rows for live inbound calls).
    connection_status = Column(String(30), nullable=False, server_default="connected")

    # FK to the call_requests row that triggered this session (outbound only).
    # NULL for inbound calls and all pre-Phase-1 rows.
    call_request_id = Column(
        Integer, ForeignKey("call_requests.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'completed', 'failed', 'no_answer', 'voicemail', 'cancelled')",
            name="ck_calls_status",
        ),
        CheckConstraint(
            "connection_status IN "
            "('not_attempted', 'attempted', 'connected', 'failed_pre_connect')",
            name="ck_calls_connection_status",
        ),
        Index("idx_calls_tenant_started", "tenant_id", "started_at"),
    )

    turns = relationship(
        "CallTurn",
        back_populates="call",
        cascade="all, delete-orphan",
        order_by="CallTurn.started_at",
    )
    events = relationship("CallEvent", back_populates="call", cascade="all, delete-orphan")


class CallTurn(Base):
    """
    One row per conversational turn — one caller utterance or one agent
    response. Written by the voice gateway as SH-11 (turn management) lands.
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
    event_type = Column(
        String(50), nullable=False
    )  # barge_in | provider_fallback | stt_failure | ...
    payload = Column(_JSONB, nullable=True)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_call_events_tenant_call", "tenant_id", "call_id"),)

    call = relationship("Call", back_populates="events")


class AuditLog(Base):
    """
    One row per sensitive action — role changes, cross-tenant access attempts,
    admin actions on a client account (NK-16).
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


class CallJob(Base):
    """
    Phase 6 — durable background job/event record.

    Deliberately NOT the same table as CallEvent: CallEvent is an immutable
    audit trail with no lifecycle of its own; a CallJob is mutable
    work-in-progress with explicit state, attempt counting, and retry
    scheduling.

    The partial unique index on (provider_call_id, event_type) is the
    authoritative idempotency guarantee: a duplicate webhook delivery hits a
    unique-constraint violation on INSERT, not a race-prone read-then-write
    check.
    """

    __tablename__ = "call_jobs"

    job_id = Column(String(36), primary_key=True, default=lambda: str(_uuid.uuid4()))
    tenant_id = Column(String(255), nullable=True, index=True)
    call_id = Column(String(36), ForeignKey("calls.call_id", ondelete="SET NULL"), nullable=True)
    provider_call_id = Column(String(255), nullable=True)
    event_type = Column(String(50), nullable=False)
    payload = Column(_JSONB, nullable=True)

    # queued -> processing -> completed
    #                    \-> retrying -> processing (loop until terminal)
    #                    \-> failed (terminal, no further retries)
    status = Column(String(20), nullable=False, server_default="queued")
    attempts = Column(Integer, nullable=False, server_default="0")
    max_attempts = Column(Integer, nullable=False, server_default="5")
    last_error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    available_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed', 'retrying')",
            name="ck_call_jobs_status",
        ),
        Index("idx_call_jobs_status_available", "status", "available_at"),
        Index("idx_call_jobs_tenant_status", "tenant_id", "status"),
        Index("idx_call_jobs_call_id", "call_id"),
        Index(
            "uq_call_jobs_provider_event",
            "provider_call_id",
            "event_type",
            unique=True,
            postgresql_where=text("provider_call_id IS NOT NULL"),
            sqlite_where=text("provider_call_id IS NOT NULL"),
        ),
    )


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


class Campaign(Base):
    """
    An outbound calling campaign: a named set of contacts + a calling
    workflow + schedule. Campaigns are tenant-scoped (client_id) and
    isolated by the same RLS policy as call_requests.

    status lifecycle: draft → scheduled → running → paused → completed | cancelled
    """

    __tablename__ = "campaigns"

    id = Column(String(36), primary_key=True, default=lambda: str(_uuid.uuid4()))
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    purpose = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, server_default="draft")
    # Calling schedule (nullable = immediate / manual start)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    # Retry config
    max_retries = Column(Integer, nullable=False, server_default="2")
    retry_delay_minutes = Column(Integer, nullable=False, server_default="60")
    # Progress counters — updated as call jobs complete
    total_contacts = Column(Integer, nullable=False, server_default="0")
    queued_count = Column(Integer, nullable=False, server_default="0")
    completed_count = Column(Integer, nullable=False, server_default="0")
    failed_count = Column(Integer, nullable=False, server_default="0")
    no_answer_count = Column(Integer, nullable=False, server_default="0")
    created_by = Column(String(36), ForeignKey("admin_users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'scheduled', 'running', 'paused', 'completed', 'cancelled')",
            name="ck_campaigns_status",
        ),
        Index("idx_campaigns_client_id", "client_id"),
    )

    client = relationship("Client")
    contacts = relationship("CampaignContact", back_populates="campaign", cascade="all, delete-orphan")


class CampaignContact(Base):
    """
    One row per contact in a campaign. Tracks per-contact call state.
    customer_id links to the canonical Customer record.
    """

    __tablename__ = "campaign_contacts"

    id = Column(String(36), primary_key=True, default=lambda: str(_uuid.uuid4()))
    campaign_id = Column(String(36), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    customer_id = Column(String(36), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    # Extra per-row data from the uploaded sheet (JSONB dict of column→value)
    row_data = Column(_JSONB, nullable=True)
    status = Column(String(20), nullable=False, server_default="queued")
    attempts = Column(Integer, nullable=False, server_default="0")
    call_request_id = Column(Integer, ForeignKey("call_requests.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'dialing', 'completed', 'failed', 'no_answer', 'skipped')",
            name="ck_campaign_contacts_status",
        ),
        Index("idx_campaign_contacts_campaign_id", "campaign_id"),
    )

    campaign = relationship("Campaign", back_populates="contacts")
    customer = relationship("Customer")
