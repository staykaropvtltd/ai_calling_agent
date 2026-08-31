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

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user
from src.database import get_db
from src.models import Caller, Client, Customer, PhoneNumberRoute, User
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
