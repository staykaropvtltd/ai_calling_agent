"""Client-facing API router (/client/*).

Authorization: tenant_admin and agent roles only.
super_admin uses /admin/* for platform management and has no account here.

Every query is scoped to the authenticated user's own tenant — the client_id
comes from the JWT, never from a URL parameter. PostgreSQL RLS (NK-07,
alembic/versions/df467b3bdd3f) provides a second independent enforcement layer
via get_tenant_scoped_db.
"""

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Optional

import csv
import io
import uuid as _uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user
from src.database import get_db
from src.models import Call, CallJob, CallTurn, Campaign, CampaignContact, Caller, Client, Customer, PhoneNumberRoute, User
from src.tenant import get_tenant_scoped_db

logger = logging.getLogger("staykaro.client")

router = APIRouter(prefix="/client", tags=["client"])


# ── Authorization ─────────────────────────────────────────────────────────────


def _require_client(user: dict = Depends(get_current_user)) -> dict:
    """Allows tenant_admin and agent — the two roles that belong to a client.
    super_admin is deliberately excluded: they manage the platform via /admin/*.
    Every endpoint that uses this dependency MUST scope its queries to
    user['client_id'] from the JWT, never accept a tenant/client id from the
    request URL or body.
    """
    role = user.get("role")
    if role not in ("tenant_admin", "agent"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client account required. Platform admins use /admin/*.",
        )
    if not user.get("client_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token has no tenant assigned. Contact your administrator.",
        )
    return user


def _require_client_admin(user: dict = Depends(_require_client)) -> dict:
    """Restricts to tenant_admin within a client. Use for management endpoints
    (users list, analytics, phone numbers, settings) that agents must not see.
    """
    if user.get("role") != "tenant_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client administrator role required.",
        )
    return user


def _paginate(total: int, page: int, per_page: int) -> int:
    return math.ceil(total / per_page) if total else 0


# ── Schemas ───────────────────────────────────────────────────────────────────


class ClientProfile(BaseModel):
    """What GET /client/me returns: the logged-in user + their tenant's details."""

    # User fields
    user_id: str
    email: str
    full_name: str
    role: str
    permissions: list[str]

    # Tenant / client fields (None for agents whose tenant has no data yet)
    tenant_id: str
    tenant_name: str
    tenant_slug: Optional[str] = None
    plan: Optional[str] = None
    tenant_status: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    max_concurrent_calls: Optional[int] = None
    api_limit: Optional[int] = None
    # Internationalisation
    country: Optional[str] = None  # ISO 3166-1 α-2
    timezone: Optional[str] = None  # IANA timezone name
    currency: Optional[str] = None  # ISO 4217
    default_language: Optional[str] = None  # BCP 47
    phone_country_code: Optional[str] = None


class UserResponse(BaseModel):
    user_id: str
    email: str
    full_name: str
    role: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None


class PaginatedUsers(BaseModel):
    data: list[UserResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class CallResponse(BaseModel):
    id: int
    customer_name: Optional[str]
    phone_number: Optional[str]
    hotel_name: Optional[str]
    check_in_date: Optional[str]
    check_out_date: Optional[str]
    created_at: Optional[datetime]
    # Phase 1 fields — present on all rows after migration c3d4e5f6a7b8
    status: Optional[str] = None
    call_type: Optional[str] = None
    is_simulation: Optional[bool] = None
    customer_id: Optional[str] = None
    connection_status: Optional[str] = None
    failure_reason: Optional[str] = None
    duration_seconds: Optional[int] = None
    outcome: Optional[str] = None

    model_config = {"from_attributes": True}


class CustomerResponse(BaseModel):
    id: str
    client_id: int
    name: Optional[str]
    phone: str
    email: Optional[str]
    language_code: Optional[str]
    timezone: Optional[str]
    country_code: Optional[str]
    notes: Optional[str]
    external_id: Optional[str]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class CustomerCreate(BaseModel):
    name: Optional[str] = None
    phone: str
    email: Optional[str] = None
    language_code: Optional[str] = None
    timezone: Optional[str] = None
    country_code: Optional[str] = None
    notes: Optional[str] = None
    external_id: Optional[str] = None


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    language_code: Optional[str] = None
    timezone: Optional[str] = None
    country_code: Optional[str] = None
    notes: Optional[str] = None
    external_id: Optional[str] = None


class PaginatedCustomers(BaseModel):
    data: list[CustomerResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class PaginatedCalls(BaseModel):
    data: list[CallResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class CallVolumeDay(BaseModel):
    date: str  # YYYY-MM-DD
    count: int


class AnalyticsResponse(BaseModel):
    total_calls: int
    calls_this_month: int
    calls_this_week: int
    daily_volume: list[CallVolumeDay]


class PhoneNumberResponse(BaseModel):
    number: str
    tenant_id: str
    agent_id: str
    provider: str
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


class PaginatedPhoneNumbers(BaseModel):
    data: list[PhoneNumberResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


# ── GET /client/me ────────────────────────────────────────────────────────────


@router.get("/me", response_model=ClientProfile)
async def get_my_profile(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(_require_client),
) -> ClientProfile:
    """Returns the authenticated user's profile combined with their tenant's
    configuration (including internationalisation settings). Accessible to
    both tenant_admin and agent.
    """
    from src.auth import _ROLE_PERMISSIONS

    client_id = user["client_id"]
    client = await db.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    role = user.get("role", "agent")
    return ClientProfile(
        user_id=str(user.get("sub", "")),
        email=user.get("email", ""),
        full_name=user.get("full_name", ""),
        role=role,
        permissions=_ROLE_PERMISSIONS.get(role, []),
        tenant_id=str(client.id),
        tenant_name=client.name,
        tenant_slug=client.slug,
        plan=client.plan,
        tenant_status=client.status,
        contact_email=client.contact_email,
        contact_phone=client.contact_phone,
        max_concurrent_calls=client.max_concurrent_calls,
        api_limit=client.api_limit,
        country=client.country,
        timezone=client.timezone,
        currency=client.currency,
        default_language=client.default_language,
        phone_country_code=client.phone_country_code,
    )


# ── GET /client/calls ─────────────────────────────────────────────────────────


@router.get("/calls", response_model=PaginatedCalls)
async def list_calls(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, description="Search by customer name or phone number"),
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_client),
) -> PaginatedCalls:
    """Paginated list of call requests for the authenticated user's tenant.
    Accessible to tenant_admin and agent — both see the full tenant's calls
    (there is no per-user filter because Caller has no placed_by column yet).
    The tenant scope is enforced by get_tenant_scoped_db (RLS) AND by the
    explicit WHERE client_id filter below (defense in depth).
    """
    client_id = user["client_id"]
    stmt = select(Caller).where(Caller.client_id == client_id).order_by(Caller.created_at.desc())

    if search:
        stmt = stmt.where(
            or_(
                Caller.customer_name.ilike(f"%{search}%"),
                Caller.phone_number.ilike(f"%{search}%"),
            )
        )

    total: int = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.offset((page - 1) * per_page).limit(per_page))).scalars().all()

    return PaginatedCalls(
        data=list(rows),
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_paginate(total, page, per_page),
    )


# ── GET /client/calls/{id} ────────────────────────────────────────────────────


@router.get("/calls/{call_id}", response_model=CallResponse)
async def get_call(
    call_id: int,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_client),
) -> CallResponse:
    client_id = user["client_id"]
    call = await db.get(Caller, call_id)
    if not call or call.client_id != client_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    return call  # type: ignore[return-value]


# ── GET /client/analytics ─────────────────────────────────────────────────────


@router.get("/analytics", response_model=AnalyticsResponse)
async def get_analytics(
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_client_admin),
) -> AnalyticsResponse:
    """Aggregate call statistics for the authenticated tenant_admin's own tenant.
    Data source: call_requests (Caller) table — each row is one POST /call request.
    """
    client_id = user["client_id"]
    base = Caller.client_id == client_id

    total_calls: int = (await db.execute(select(func.count(Caller.id)).where(base))).scalar_one()

    start_of_month = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    calls_this_month: int = (
        await db.execute(
            select(func.count(Caller.id)).where(base, Caller.created_at >= start_of_month)
        )
    ).scalar_one()

    start_of_week = datetime.now(UTC) - timedelta(days=7)
    calls_this_week: int = (
        await db.execute(
            select(func.count(Caller.id)).where(base, Caller.created_at >= start_of_week)
        )
    ).scalar_one()

    thirty_days_ago = datetime.now(UTC) - timedelta(days=30)
    date_expr = func.date(Caller.created_at)
    daily_rows = (
        await db.execute(
            select(date_expr.label("day"), func.count(Caller.id).label("cnt"))
            .where(base, Caller.created_at >= thirty_days_ago)
            .group_by(date_expr)
            .order_by(date_expr.asc())
        )
    ).all()

    return AnalyticsResponse(
        total_calls=total_calls,
        calls_this_month=calls_this_month,
        calls_this_week=calls_this_week,
        daily_volume=[CallVolumeDay(date=str(row.day), count=row.cnt) for row in daily_rows],
    )


# ── GET /client/users ─────────────────────────────────────────────────────────


@router.get("/users", response_model=PaginatedUsers)
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    role: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_client_admin),
) -> PaginatedUsers:
    client_id = user["client_id"]
    stmt = select(User).where(User.tenant_id == client_id).order_by(User.created_at.desc())
    if role:
        stmt = stmt.where(User.role == role)
    if status_filter:
        stmt = stmt.where(User.status == status_filter)

    total: int = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.offset((page - 1) * per_page).limit(per_page))).scalars().all()

    return PaginatedUsers(
        data=[
            UserResponse(
                user_id=u.id,
                email=u.email,
                full_name=u.full_name,
                role=u.role,
                status=u.status,
                created_at=u.created_at,
            )
            for u in rows
        ],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_paginate(total, page, per_page),
    )


# ── GET /client/users/{user_id} ───────────────────────────────────────────────


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_client_admin),
) -> UserResponse:
    client_id = user["client_id"]
    fetched = await db.get(User, user_id)
    if not fetched or fetched.tenant_id != client_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse(
        user_id=fetched.id,
        email=fetched.email,
        full_name=fetched.full_name,
        role=fetched.role,
        status=fetched.status,
        created_at=fetched.created_at,
    )


# ── GET /client/phone-numbers ─────────────────────────────────────────────────


@router.get("/phone-numbers", response_model=PaginatedPhoneNumbers)
async def list_phone_numbers(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(_require_client_admin),
) -> PaginatedPhoneNumbers:
    """Lists the phone number routes assigned to this tenant. Read-only;
    provisioning is done by platform admins via /admin/*.
    """
    client_id = user["client_id"]
    stmt = select(PhoneNumberRoute).where(PhoneNumberRoute.tenant_id == str(client_id))

    total: int = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.offset((page - 1) * per_page).limit(per_page))).scalars().all()

    return PaginatedPhoneNumbers(
        data=list(rows),
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_paginate(total, page, per_page),
    )


# ── GET /client/customers ─────────────────────────────────────────────────────


@router.get("/customers", response_model=PaginatedCustomers)
async def list_customers(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, description="Search by name, phone, or email"),
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_client),
) -> PaginatedCustomers:
    """Paginated customer list for the authenticated user's tenant.
    Accessible to both tenant_admin and agent.
    Tenant scope is enforced by RLS (get_tenant_scoped_db) and by the
    explicit WHERE client_id filter (defense in depth).
    """
    client_id = user["client_id"]
    stmt = (
        select(Customer).where(Customer.client_id == client_id).order_by(Customer.created_at.desc())
    )

    if search:
        stmt = stmt.where(
            or_(
                Customer.name.ilike(f"%{search}%"),
                Customer.phone.ilike(f"%{search}%"),
                Customer.email.ilike(f"%{search}%"),
            )
        )

    total: int = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.offset((page - 1) * per_page).limit(per_page))).scalars().all()

    return PaginatedCustomers(
        data=list(rows),
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_paginate(total, page, per_page),
    )


# ── GET /client/customers/{customer_id} ──────────────────────────────────────


@router.get("/customers/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: str,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_client),
) -> CustomerResponse:
    client_id = user["client_id"]
    customer = await db.get(Customer, customer_id)
    # Explicit client_id check in addition to RLS — makes cross-tenant access
    # fail with 404 (not 403) regardless of whether RLS is active in the
    # current session, and prevents information leakage via timing differences.
    if not customer or customer.client_id != client_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer  # type: ignore[return-value]


# ── POST /client/customers ────────────────────────────────────────────────────


@router.post("/customers", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_or_update_customer(
    body: CustomerCreate,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_client),
) -> CustomerResponse:
    """Create a customer record, or update the existing one if a customer with
    the same phone number already exists for this tenant (upsert-by-phone).

    Phone uniqueness is enforced by the unique index uq_customers_client_phone
    (migration c3d4e5f6a7b8). The upsert avoids 409 conflicts when the same
    phone is submitted multiple times (e.g. re-importing a contact list) and
    keeps the dataset clean with a single canonical record per contact.
    """
    client_id = user["client_id"]

    # Check for existing customer with same phone in this tenant
    existing_row = (
        await db.execute(
            select(Customer).where(
                Customer.client_id == client_id,
                Customer.phone == body.phone,
            )
        )
    ).scalar_one_or_none()

    if existing_row is not None:
        # Update the existing record with any non-null fields from the request
        if body.name is not None:
            existing_row.name = body.name
        if body.email is not None:
            existing_row.email = body.email
        if body.language_code is not None:
            existing_row.language_code = body.language_code
        if body.timezone is not None:
            existing_row.timezone = body.timezone
        if body.country_code is not None:
            existing_row.country_code = body.country_code
        if body.notes is not None:
            existing_row.notes = body.notes
        if body.external_id is not None:
            existing_row.external_id = body.external_id
        await db.commit()
        await db.refresh(existing_row)
        logger.info(
            "Customer upserted (existing): customer_id=%s client_id=%s phone=%s",
            existing_row.id,
            client_id,
            body.phone,
        )
        return existing_row  # type: ignore[return-value]

    import uuid as _uuid

    customer = Customer(
        id=str(_uuid.uuid4()),
        client_id=client_id,
        name=body.name,
        phone=body.phone,
        email=body.email,
        language_code=body.language_code,
        timezone=body.timezone,
        country_code=body.country_code,
        notes=body.notes,
        external_id=body.external_id,
    )
    db.add(customer)
    await db.commit()
    await db.refresh(customer)
    logger.info(
        "Customer created: customer_id=%s client_id=%s phone=%s",
        customer.id,
        client_id,
        body.phone,
    )
    return customer  # type: ignore[return-value]


# ── PUT /client/customers/{customer_id} ──────────────────────────────────────


@router.put("/customers/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: str,
    body: CustomerUpdate,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_client),
) -> CustomerResponse:
    """Update a customer's profile fields. Phone number is immutable after
    creation — to change a phone number create a new customer record.
    Only fields included in the request body (non-None) are updated.
    """
    client_id = user["client_id"]
    customer = await db.get(Customer, customer_id)
    if not customer or customer.client_id != client_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    if body.name is not None:
        customer.name = body.name
    if body.email is not None:
        customer.email = body.email
    if body.language_code is not None:
        customer.language_code = body.language_code
    if body.timezone is not None:
        customer.timezone = body.timezone
    if body.country_code is not None:
        customer.country_code = body.country_code
    if body.notes is not None:
        customer.notes = body.notes
    if body.external_id is not None:
        customer.external_id = body.external_id

    await db.commit()
    await db.refresh(customer)
    return customer  # type: ignore[return-value]


# ── GET /client/calls/{id}/transcript ─────────────────────────────────────────


class TranscriptTurnResponse(BaseModel):
    turn_id: str
    speaker: str  # caller | agent
    text: str
    started_at: Optional[datetime]
    language_code: Optional[str]

    model_config = {"from_attributes": True}


@router.get("/calls/{call_id}/transcript", response_model=list[TranscriptTurnResponse])
async def get_call_transcript(
    call_id: int,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_client),
) -> list[TranscriptTurnResponse]:
    """Returns the conversation transcript for a call request.

    The Caller (call_request) record links to a Call record via
    telephony_call_id. Call records own CallTurn rows. This endpoint
    resolves that chain and returns turns ordered by started_at.

    Returns an empty list when:
    - the call has not been initiated yet (telephony_call_id is NULL)
    - the voice gateway has not written any turns yet
    - the Call record is not in this tenant's calls (tenant safety)
    """
    client_id = user["client_id"]
    caller = await db.get(Caller, call_id)
    if not caller or caller.client_id != client_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")

    if not caller.telephony_call_id:
        return []

    # Resolve the voice-gateway Call record for this call request.
    # tenant_id on Call is str(client_id) — verify to prevent cross-tenant leakage.
    call_row = (
        await db.execute(
            select(Call).where(
                Call.call_id == caller.telephony_call_id,
                Call.tenant_id == str(client_id),
            )
        )
    ).scalar_one_or_none()

    if not call_row:
        return []

    turn_rows = (
        await db.execute(
            select(CallTurn)
            .where(CallTurn.call_id == call_row.call_id)
            .order_by(CallTurn.started_at.asc())
        )
    ).scalars().all()

    return [TranscriptTurnResponse.model_validate(t) for t in turn_rows]


# ── Campaigns ─────────────────────────────────────────────────────────────────

VALID_CAMPAIGN_STATUSES = {"draft", "scheduled", "running", "paused", "completed", "cancelled"}


class CampaignCreate(BaseModel):
    name: str
    description: Optional[str] = None
    purpose: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    max_retries: int = 2
    retry_delay_minutes: int = 60


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    purpose: Optional[str] = None
    status: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    max_retries: Optional[int] = None
    retry_delay_minutes: Optional[int] = None


class CampaignResponse(BaseModel):
    id: str
    client_id: int
    name: str
    description: Optional[str]
    purpose: Optional[str]
    status: str
    scheduled_at: Optional[datetime]
    max_retries: int
    retry_delay_minutes: int
    total_contacts: int
    queued_count: int
    completed_count: int
    failed_count: int
    no_answer_count: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class PaginatedCampaigns(BaseModel):
    data: list[CampaignResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


@router.post("/campaigns", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CampaignCreate,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_client_admin),
) -> CampaignResponse:
    client_id = user["client_id"]
    campaign = Campaign(
        id=str(_uuid.uuid4()),
        client_id=client_id,
        name=body.name,
        description=body.description,
        purpose=body.purpose,
        scheduled_at=body.scheduled_at,
        max_retries=body.max_retries,
        retry_delay_minutes=body.retry_delay_minutes,
        created_by=str(user.get("sub", "")),
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign  # type: ignore[return-value]


@router.get("/campaigns", response_model=PaginatedCampaigns)
async def list_campaigns(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_client_admin),
) -> PaginatedCampaigns:
    client_id = user["client_id"]
    stmt = (
        select(Campaign)
        .where(Campaign.client_id == client_id)
        .order_by(Campaign.created_at.desc())
    )
    if status_filter:
        stmt = stmt.where(Campaign.status == status_filter)

    total: int = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.offset((page - 1) * per_page).limit(per_page))).scalars().all()

    return PaginatedCampaigns(
        data=list(rows),
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_paginate(total, page, per_page),
    )


@router.get("/campaigns/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: str,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_client_admin),
) -> CampaignResponse:
    client_id = user["client_id"]
    campaign = await db.get(Campaign, campaign_id)
    if not campaign or campaign.client_id != client_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return campaign  # type: ignore[return-value]


@router.put("/campaigns/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: str,
    body: CampaignUpdate,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_client_admin),
) -> CampaignResponse:
    client_id = user["client_id"]
    campaign = await db.get(Campaign, campaign_id)
    if not campaign or campaign.client_id != client_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    updates = body.model_dump(exclude_none=True)
    if "status" in updates and updates["status"] not in VALID_CAMPAIGN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status must be one of {sorted(VALID_CAMPAIGN_STATUSES)}",
        )

    was_running = campaign.status == "running"
    for field, value in updates.items():
        setattr(campaign, field, value)

    # Queue outbound calls when campaign transitions to "running".
    # This covers both a fresh start (draft/scheduled → running) and a resume
    # (paused → running).  We never re-queue contacts that are already in
    # progress (call_request_id is set) or permanently done (completed/skipped).
    if campaign.status == "running" and not was_running:
        await _queue_campaign_contacts(db, campaign, client_id)

    await db.commit()
    await db.refresh(campaign)
    return campaign  # type: ignore[return-value]


async def _queue_campaign_contacts(db: AsyncSession, campaign: Campaign, client_id: int) -> None:
    """Create Caller work-items and CallJob records for every contact that is
    ready to be called.  Covers both first-time queuing (status='queued',
    no call_request_id) and retry-eligible contacts (failed/no_answer,
    attempts < max_retries).  All writes land in the same transaction as the
    campaign status update so no contacts are silently dropped on failure."""
    from datetime import UTC, datetime

    # Fresh contacts: imported but never dialled
    fresh_result = await db.execute(
        select(CampaignContact)
        .where(
            CampaignContact.campaign_id == campaign.id,
            CampaignContact.status == "queued",
            CampaignContact.call_request_id.is_(None),
        )
    )
    fresh = list(fresh_result.scalars().all())

    # Retry-eligible contacts: failed/no_answer but haven't exhausted retries
    retry_result = await db.execute(
        select(CampaignContact)
        .where(
            CampaignContact.campaign_id == campaign.id,
            CampaignContact.status.in_(["failed", "no_answer"]),
            CampaignContact.attempts < campaign.max_retries,
        )
    )
    retries = list(retry_result.scalars().all())

    if not fresh and not retries:
        logger.info("Campaign %s has no contacts to queue", campaign.id)
        return

    queued_count = 0
    for contact in fresh + retries:
        customer = await db.get(Customer, contact.customer_id)
        if customer is None or not customer.phone:
            contact.status = "skipped"
            continue

        caller = Caller(
            client_id=client_id,
            customer_id=customer.id,
            phone_number=customer.phone,
            customer_name=customer.name,
            status="queued",
            call_type="outbound",
            # is_simulation is set to True by the integration-service when
            # Exotel credentials are absent — starts as False here.
            is_simulation=False,
        )
        db.add(caller)
        await db.flush()  # populate caller.id before referencing it in the job

        contact.call_request_id = caller.id
        contact.status = "dialing"

        job = CallJob(
            tenant_id=str(client_id),
            event_type="outbound_dial",
            payload={
                "caller_id": caller.id,
                "campaign_contact_id": str(contact.id),
                "campaign_id": str(campaign.id),
                "phone_number": customer.phone,
                "customer_name": customer.name or "",
                "tenant_id": str(client_id),
            },
        )
        db.add(job)
        queued_count += 1

    if queued_count:
        campaign.queued_count = (campaign.queued_count or 0) + queued_count
        logger.info(
            "Campaign %s: queued %d outbound call(s)", campaign.id, queued_count
        )


# ── CSV/Sheet Upload ──────────────────────────────────────────────────────────

_MAX_CSV_ROWS = 5000
_MAX_CSV_BYTES = 10 * 1024 * 1024  # 10 MB


class UploadPreviewRow(BaseModel):
    row_number: int
    data: dict
    error: Optional[str] = None


class UploadPreviewResponse(BaseModel):
    total_rows: int
    valid_rows: int
    invalid_rows: int
    columns: list[str]
    preview: list[UploadPreviewRow]


class SheetImportRequest(BaseModel):
    campaign_id: str
    phone_column: str
    name_column: Optional[str] = None
    email_column: Optional[str] = None


@router.post("/upload/preview", response_model=UploadPreviewResponse)
async def preview_upload(
    file: UploadFile = File(...),
    user: dict = Depends(_require_client_admin),
) -> UploadPreviewResponse:
    """Parse an uploaded CSV and return a preview with column detection.
    Does NOT create any database records — purely for UI preview + column mapping.
    Accepts .csv files only (XLSX support requires openpyxl which is optional).
    Max 10 MB / 5000 rows.
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .csv files are supported. Convert your Excel file to CSV first.",
        )

    raw = await file.read()
    if len(raw) > _MAX_CSV_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {_MAX_CSV_BYTES // (1024 * 1024)} MB.",
        )

    try:
        text = raw.decode("utf-8-sig")  # strip BOM if present
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    columns: list[str] = list(reader.fieldnames or [])
    if not columns:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV file has no header row or could not be parsed.",
        )

    preview_rows: list[UploadPreviewRow] = []
    valid = 0
    invalid = 0
    total = 0

    for i, row in enumerate(reader):
        if i >= _MAX_CSV_ROWS:
            break
        total += 1
        row_error: Optional[str] = None
        # Basic validation: check any column likely to contain a phone has a value
        has_phone_candidate = any(
            "phone" in col.lower() or "mobile" in col.lower() or "number" in col.lower()
            for col in columns
        )
        if has_phone_candidate:
            phone_cols = [
                col
                for col in columns
                if "phone" in col.lower() or "mobile" in col.lower() or "number" in col.lower()
            ]
            if not any(row.get(col, "").strip() for col in phone_cols):
                row_error = "No phone number found"
                invalid += 1
            else:
                valid += 1
        else:
            valid += 1

        if len(preview_rows) < 20:
            preview_rows.append(
                UploadPreviewRow(row_number=i + 1, data=dict(row), error=row_error)
            )

    return UploadPreviewResponse(
        total_rows=total,
        valid_rows=valid,
        invalid_rows=invalid,
        columns=columns,
        preview=preview_rows,
    )


@router.post("/upload/import", status_code=status.HTTP_201_CREATED)
async def import_sheet(
    file: UploadFile = File(...),
    campaign_id: str = Query(...),
    phone_column: str = Query(...),
    name_column: Optional[str] = Query(None),
    email_column: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_client_admin),
) -> dict:
    """Import contacts from a CSV into a campaign.

    For each valid row:
    1. Upsert the Customer record (same upsert-by-phone as POST /client/customers).
    2. Create a CampaignContact linking the customer to the campaign.
    3. Update Campaign.total_contacts.

    The actual call initiation (queue → dial) is triggered separately by
    updating the campaign status to 'running' via PUT /client/campaigns/{id}.
    """
    client_id = user["client_id"]

    # Verify campaign belongs to this tenant
    campaign = await db.get(Campaign, campaign_id)
    if not campaign or campaign.client_id != client_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    if campaign.status not in ("draft", "scheduled"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot import contacts into a campaign with status '{campaign.status}'.",
        )

    raw = await file.read()
    if len(raw) > _MAX_CSV_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large.",
        )

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    imported = 0
    skipped = 0

    for i, row in enumerate(reader):
        if i >= _MAX_CSV_ROWS:
            break

        phone_raw = row.get(phone_column, "").strip()
        if not phone_raw:
            skipped += 1
            continue

        # Normalise phone: ensure it starts with +
        phone = phone_raw if phone_raw.startswith("+") else f"+{phone_raw}"
        name = (row.get(name_column or "", "") or "").strip() or None
        email = (row.get(email_column or "", "") or "").strip() or None

        # Upsert customer
        existing = (
            await db.execute(
                select(Customer).where(
                    Customer.client_id == client_id,
                    Customer.phone == phone,
                )
            )
        ).scalar_one_or_none()

        if existing:
            customer = existing
            if name:
                customer.name = name
            if email:
                customer.email = email
        else:
            customer = Customer(
                id=str(_uuid.uuid4()),
                client_id=client_id,
                name=name,
                phone=phone,
                email=email,
            )
            db.add(customer)
            await db.flush()

        # Create campaign contact
        contact = CampaignContact(
            id=str(_uuid.uuid4()),
            campaign_id=campaign_id,
            customer_id=customer.id,
            row_data={k: v for k, v in row.items()},
        )
        db.add(contact)
        imported += 1

    campaign.total_contacts = (campaign.total_contacts or 0) + imported
    await db.commit()

    return {"imported": imported, "skipped": skipped, "campaign_id": campaign_id}
