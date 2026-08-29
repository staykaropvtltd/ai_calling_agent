import logging
import math
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user, hash_password
from src.database import get_db
from src.models import AuditLog, Caller, Client, User
from src.tenant import get_tenant_scoped_db

logger = logging.getLogger("staykaro.admin")

router = APIRouter(prefix="/admin", tags=["admin"])


# ── RBAC ──────────────────────────────────────────────────────────────────────


def _require_super_admin(user: dict = Depends(get_current_user)) -> dict:
    """Only tokens with role=super_admin may access admin management routes."""
    if user.get("role") != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="super_admin role required",
        )
    return user


def _require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Allows super_admin (unrestricted) and tenant_admin (own-tenant only).
    Routes using this dependency MUST scope queries by checking user['role'] and
    using user.get('client_id') rather than the tenant_id query parameter.
    """
    if user.get("role") not in ("super_admin", "tenant_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin role required",
        )
    return user


# ── Schemas — Clients ─────────────────────────────────────────────────────────

VALID_PLANS = {"starter", "pro", "enterprise"}
VALID_CLIENT_STATUSES = {"active", "suspended", "inactive"}
VALID_USER_ROLES = {"super_admin", "tenant_admin", "agent"}
VALID_USER_STATUSES = {"active", "suspended"}


class ClientCreate(BaseModel):
    name: str
    slug: str
    plan: str = "starter"
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    api_limit: int = 100
    max_concurrent_calls: int = 10


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    plan: Optional[str] = None
    status: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    api_limit: Optional[int] = None
    max_concurrent_calls: Optional[int] = None


class ClientResponse(BaseModel):
    id: int
    name: str
    slug: Optional[str]
    plan: Optional[str]
    status: Optional[str]
    contact_email: Optional[str]
    contact_phone: Optional[str]
    api_limit: Optional[int]
    max_concurrent_calls: Optional[int]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class PaginatedClients(BaseModel):
    data: list[ClientResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class ClientStats(BaseModel):
    client_id: int
    total_calls: int
    calls_this_month: int
    active_users: int
    plan_call_limit: int
    plan_usage_pct: float


# ── Schemas — Users ───────────────────────────────────────────────────────────


class UserCreate(BaseModel):
    email: str
    full_name: str
    role: str = "agent"
    tenant_id: Optional[int] = None
    # Optional: a user created without one has no password_hash and cannot
    # log in via /auth/login until an admin sets one (PUT .../password).
    password: Optional[str] = Field(default=None, min_length=8, max_length=72)


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=72)


class UserResponse(BaseModel):
    user_id: str
    email: str
    full_name: str
    role: Optional[str] = None
    tenant_id: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None


def _user_to_response(user: User) -> UserResponse:
    return UserResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        tenant_id=str(user.tenant_id) if user.tenant_id is not None else None,
        status=user.status,
        created_at=user.created_at,
    )


class PaginatedUsers(BaseModel):
    data: list[UserResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


# ── Schemas — Calls ───────────────────────────────────────────────────────────


class CallResponse(BaseModel):
    id: int
    customer_name: Optional[str]
    phone_number: Optional[str]
    hotel_name: Optional[str]
    check_in_date: Optional[str]
    check_out_date: Optional[str]
    client_id: Optional[int]
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


class PaginatedCalls(BaseModel):
    data: list[CallResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


# ── Helpers ───────────────────────────────────────────────────────────────────


def _paginate(total: int, page: int, per_page: int) -> int:
    return math.ceil(total / per_page) if total else 0


def _client_audit_snapshot(client: Client) -> dict:
    """Fields safe to store in an audit row — no secrets, nothing internal-only."""
    return {
        "id": client.id,
        "name": client.name,
        "slug": client.slug,
        "plan": client.plan,
        "status": client.status,
        "contact_email": client.contact_email,
        "contact_phone": client.contact_phone,
        "api_limit": client.api_limit,
        "max_concurrent_calls": client.max_concurrent_calls,
    }


def _user_audit_snapshot(user: User) -> dict:
    """Deliberately excludes password_hash — Testing Guide §6: no log line
    may leak a secret or password hash."""
    return {
        "user_id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "tenant_id": user.tenant_id,
        "status": user.status,
    }


async def _write_audit_log(
    db: AsyncSession,
    *,
    actor: dict,
    action: str,
    tenant_id: Optional[int] = None,
    before: Optional[dict] = None,
    after: Optional[dict] = None,
) -> None:
    """NK-16 — one row per sensitive action (Database Design §5, audit_logs).
    Best-effort: a failure here must never roll back or fail the mutation it
    describes, so it's logged and swallowed rather than raised — an admin
    action succeeding is more important than its own audit trail existing.
    """
    try:
        db.add(
            AuditLog(
                tenant_id=str(tenant_id) if tenant_id is not None else None,
                user_id=actor.get("sub"),
                action=action,
                before_value=before,
                after_value=after,
            )
        )
        await db.commit()
    except Exception:
        logger.exception("Failed to write audit log for action=%s", action)
        await db.rollback()


# ── Client endpoints ──────────────────────────────────────────────────────────


@router.post("/clients", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(
    body: ClientCreate,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_super_admin),
) -> Client:
    if body.plan not in VALID_PLANS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"plan must be one of {sorted(VALID_PLANS)}",
        )
    existing = await db.execute(select(Client).where(Client.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already exists")
    client = Client(**body.model_dump())
    db.add(client)
    await db.commit()
    await db.refresh(client)
    logger.info("Client created: id=%s slug=%s", client.id, client.slug)
    await _write_audit_log(
        db,
        actor=user,
        action="client.create",
        tenant_id=client.id,
        after=_client_audit_snapshot(client),
    )
    return client


@router.get("/clients", response_model=PaginatedClients)
async def list_clients(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_require_super_admin),
) -> PaginatedClients:
    stmt = select(Client)
    if status_filter:
        stmt = stmt.where(Client.status == status_filter)
    if search:
        stmt = stmt.where(Client.name.ilike(f"%{search}%"))

    total: int = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.offset((page - 1) * per_page).limit(per_page))).scalars().all()

    return PaginatedClients(
        data=list(rows),
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_paginate(total, page, per_page),
    )


@router.get("/clients/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_require_super_admin),
) -> Client:
    client = await db.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    return client


@router.put("/clients/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: int,
    body: ClientUpdate,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_super_admin),
) -> Client:
    client = await db.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    updates = body.model_dump(exclude_none=True)
    if "plan" in updates and updates["plan"] not in VALID_PLANS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"plan must be one of {sorted(VALID_PLANS)}",
        )
    if "status" in updates and updates["status"] not in VALID_CLIENT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status must be one of {sorted(VALID_CLIENT_STATUSES)}",
        )
    if "slug" in updates and updates["slug"] != client.slug:
        clash = await db.execute(select(Client).where(Client.slug == updates["slug"]))
        if clash.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already exists")

    before = _client_audit_snapshot(client)
    for field, value in updates.items():
        setattr(client, field, value)
    await db.commit()
    await db.refresh(client)
    await _write_audit_log(
        db,
        actor=user,
        action="client.update",
        tenant_id=client.id,
        before=before,
        after=_client_audit_snapshot(client),
    )
    return client


@router.delete("/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: int,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_super_admin),
) -> None:
    """Soft delete — sets status to 'inactive'. Data is retained."""
    client = await db.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    before = _client_audit_snapshot(client)
    client.status = "inactive"
    await db.commit()
    logger.info("Client soft-deleted: id=%s", client_id)
    await _write_audit_log(
        db,
        actor=user,
        action="client.delete",
        tenant_id=client.id,
        before=before,
        after=_client_audit_snapshot(client),
    )


@router.get("/clients/{client_id}/stats", response_model=ClientStats)
async def get_client_stats(
    client_id: int,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    _user: dict = Depends(_require_super_admin),
) -> ClientStats:
    client = await db.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    total_calls: int = (
        await db.execute(select(func.count(Caller.id)).where(Caller.client_id == client_id))
    ).scalar_one()

    start_of_month = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    calls_this_month: int = (
        await db.execute(
            select(func.count(Caller.id)).where(
                Caller.client_id == client_id,
                Caller.created_at >= start_of_month,
            )
        )
    ).scalar_one()

    active_users: int = (
        await db.execute(
            select(func.count(User.id)).where(
                User.tenant_id == client_id,
                User.status == "active",
            )
        )
    ).scalar_one()

    limit = client.api_limit or 0
    usage_pct = round((total_calls / limit) * 100, 1) if limit else 0.0

    return ClientStats(
        client_id=client_id,
        total_calls=total_calls,
        calls_this_month=calls_this_month,
        active_users=active_users,
        plan_call_limit=limit,
        plan_usage_pct=usage_pct,
    )


# ── User endpoints ────────────────────────────────────────────────────────────


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    actor: dict = Depends(_require_super_admin),
) -> UserResponse:
    if body.role not in VALID_USER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"role must be one of {sorted(VALID_USER_ROLES)}",
        )
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already exists",
        )
    if body.tenant_id is not None:
        tenant = await db.get(Client, body.tenant_id)
        if not tenant:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    fields = body.model_dump(exclude={"password"})
    user = User(**fields, password_hash=hash_password(body.password) if body.password else None)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("User created: id=%s email=%s role=%s", user.id, user.email, user.role)
    await _write_audit_log(
        db,
        actor=actor,
        action="user.create",
        tenant_id=user.tenant_id,
        after=_user_audit_snapshot(user),
    )
    return _user_to_response(user)


@router.get("/users", response_model=PaginatedUsers)
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    tenant_id: Optional[int] = Query(None),
    role: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_admin),
) -> PaginatedUsers:
    stmt = select(User)

    if user.get("role") == "tenant_admin":
        # Tenant isolation: ignore the tenant_id query param; always bind to the
        # client_id embedded in the JWT so a caller cannot escalate to another tenant.
        jwt_tenant_id = user.get("client_id")
        if not jwt_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="tenant_admin token has no tenant assigned",
            )
        stmt = stmt.where(User.tenant_id == jwt_tenant_id)
    else:
        # super_admin: apply the optional query param filter.
        if tenant_id is not None:
            stmt = stmt.where(User.tenant_id == tenant_id)

    if role:
        stmt = stmt.where(User.role == role)
    if status_filter:
        stmt = stmt.where(User.status == status_filter)

    total: int = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.offset((page - 1) * per_page).limit(per_page))).scalars().all()

    return PaginatedUsers(
        data=[_user_to_response(u) for u in rows],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_paginate(total, page, per_page),
    )


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_admin),
) -> UserResponse:
    fetched = await db.get(User, user_id)
    if not fetched:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    # tenant_admin may only view users belonging to their own tenant.
    if user.get("role") == "tenant_admin" and fetched.tenant_id != user.get("client_id"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return _user_to_response(fetched)


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UserUpdate,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    actor: dict = Depends(_require_super_admin),
) -> UserResponse:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    updates = body.model_dump(exclude_none=True)
    if "role" in updates and updates["role"] not in VALID_USER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"role must be one of {sorted(VALID_USER_ROLES)}",
        )
    if "status" in updates and updates["status"] not in VALID_USER_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status must be one of {sorted(VALID_USER_STATUSES)}",
        )
    if "password" in updates:
        # password isn't a User column — password_hash is. Left as a plain
        # setattr, this would silently no-op instead of persisting.
        user.password_hash = hash_password(updates.pop("password"))

    before = _user_audit_snapshot(user)
    for field, value in updates.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    # Database Design §5 names "role changes" explicitly as an audited action —
    # a single "user.update" action covers it (before/after.role differing is
    # the role-change signal), rather than a separate action string, since
    # every other field on this same request is just as security-relevant
    # (status, e.g.) and shouldn't fall outside the audit trail.
    await _write_audit_log(
        db,
        actor=actor,
        action="user.update",
        tenant_id=user.tenant_id,
        before=before,
        after=_user_audit_snapshot(user),
    )
    return _user_to_response(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    actor: dict = Depends(_require_super_admin),
) -> None:
    """Soft delete — sets status to 'suspended'. Data is retained."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    before = _user_audit_snapshot(user)
    user.status = "suspended"
    await db.commit()
    logger.info("User soft-deleted (suspended): id=%s", user_id)
    await _write_audit_log(
        db,
        actor=actor,
        action="user.delete",
        tenant_id=user.tenant_id,
        before=before,
        after=_user_audit_snapshot(user),
    )


# ── Call log endpoints (read-only) ────────────────────────────────────────────


@router.get("/calls", response_model=PaginatedCalls)
async def list_calls(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    tenant_id: Optional[int] = Query(None, description="Filter by client/tenant id"),
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_admin),
) -> PaginatedCalls:
    stmt = select(Caller)

    if user.get("role") == "tenant_admin":
        # Tenant isolation: ignore the tenant_id query param; always bind to the
        # client_id in the JWT so a caller cannot escalate to another tenant.
        jwt_tenant_id = user.get("client_id")
        if not jwt_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="tenant_admin token has no tenant assigned",
            )
        stmt = stmt.where(Caller.client_id == jwt_tenant_id)
    else:
        # super_admin: apply the optional query param filter.
        if tenant_id is not None:
            stmt = stmt.where(Caller.client_id == tenant_id)

    total: int = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.offset((page - 1) * per_page).limit(per_page))).scalars().all()

    return PaginatedCalls(
        data=list(rows),
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_paginate(total, page, per_page),
    )


@router.get("/calls/{call_id}", response_model=CallResponse)
async def get_call(
    call_id: int,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_admin),
) -> Caller:
    call = await db.get(Caller, call_id)
    if not call:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    # tenant_admin may only view calls belonging to their own tenant.
    if user.get("role") == "tenant_admin" and call.client_id != user.get("client_id"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return call


# ── Schemas — Tenants (frontend-facing alias of Clients) ─────────────────────
# The admin-dashboard TypeScript types use "tenant" terminology and expect
# tenant_id (str) rather than id (int). These schemas bridge that gap while
# keeping the internal Client model unchanged.


class TenantResponse(BaseModel):
    tenant_id: str
    name: str
    slug: Optional[str] = None
    plan: Optional[str] = None
    status: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    api_limit: Optional[int] = None
    max_concurrent_calls: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PaginatedTenants(BaseModel):
    data: list[TenantResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class TenantStats(BaseModel):
    tenant_id: str
    total_calls: int
    calls_this_month: int
    active_users: int
    plan_call_limit: int
    plan_usage_pct: float


def _client_to_tenant(client: Client) -> TenantResponse:
    return TenantResponse(
        tenant_id=str(client.id),
        name=client.name,
        slug=client.slug,
        plan=client.plan,
        status=client.status,
        contact_email=client.contact_email,
        contact_phone=client.contact_phone,
        api_limit=client.api_limit,
        max_concurrent_calls=client.max_concurrent_calls,
        created_at=client.created_at,
        updated_at=client.updated_at,
    )


# ── Tenant endpoints (/admin/tenants) ─────────────────────────────────────────


@router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: ClientCreate,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_super_admin),
) -> TenantResponse:
    if body.plan not in VALID_PLANS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"plan must be one of {sorted(VALID_PLANS)}",
        )
    existing = await db.execute(select(Client).where(Client.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already exists")
    client = Client(**body.model_dump())
    db.add(client)
    await db.commit()
    await db.refresh(client)
    logger.info("Tenant created: id=%s slug=%s", client.id, client.slug)
    await _write_audit_log(
        db,
        actor=user,
        action="tenant.create",
        tenant_id=client.id,
        after=_client_audit_snapshot(client),
    )
    return _client_to_tenant(client)


@router.get("/tenants", response_model=PaginatedTenants)
async def list_tenants(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_require_super_admin),
) -> PaginatedTenants:
    stmt = select(Client)
    if status_filter:
        stmt = stmt.where(Client.status == status_filter)
    if search:
        stmt = stmt.where(Client.name.ilike(f"%{search}%"))

    total: int = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.offset((page - 1) * per_page).limit(per_page))).scalars().all()

    return PaginatedTenants(
        data=[_client_to_tenant(c) for c in rows],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_paginate(total, page, per_page),
    )


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_require_super_admin),
) -> TenantResponse:
    client = await db.get(Client, tenant_id)
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return _client_to_tenant(client)


@router.put("/tenants/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: int,
    body: ClientUpdate,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_super_admin),
) -> TenantResponse:
    client = await db.get(Client, tenant_id)
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    updates = body.model_dump(exclude_none=True)
    if "plan" in updates and updates["plan"] not in VALID_PLANS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"plan must be one of {sorted(VALID_PLANS)}",
        )
    if "status" in updates and updates["status"] not in VALID_CLIENT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status must be one of {sorted(VALID_CLIENT_STATUSES)}",
        )
    if "slug" in updates and updates["slug"] != client.slug:
        clash = await db.execute(select(Client).where(Client.slug == updates["slug"]))
        if clash.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already exists")

    before = _client_audit_snapshot(client)
    for field, value in updates.items():
        setattr(client, field, value)
    await db.commit()
    await db.refresh(client)
    await _write_audit_log(
        db,
        actor=user,
        action="tenant.update",
        tenant_id=client.id,
        before=before,
        after=_client_audit_snapshot(client),
    )
    return _client_to_tenant(client)


@router.delete("/tenants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: int,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_super_admin),
) -> None:
    """Soft delete — sets status to 'inactive'. Data is retained."""
    client = await db.get(Client, tenant_id)
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    before = _client_audit_snapshot(client)
    client.status = "inactive"
    await db.commit()
    logger.info("Tenant soft-deleted: id=%s", tenant_id)
    await _write_audit_log(
        db,
        actor=user,
        action="tenant.delete",
        tenant_id=client.id,
        before=before,
        after=_client_audit_snapshot(client),
    )


@router.get("/tenants/{tenant_id}/stats", response_model=TenantStats)
async def get_tenant_stats(
    tenant_id: int,
    db: AsyncSession = Depends(get_tenant_scoped_db),
    _user: dict = Depends(_require_super_admin),
) -> TenantStats:
    client = await db.get(Client, tenant_id)
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    total_calls: int = (
        await db.execute(select(func.count(Caller.id)).where(Caller.client_id == tenant_id))
    ).scalar_one()

    start_of_month = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    calls_this_month: int = (
        await db.execute(
            select(func.count(Caller.id)).where(
                Caller.client_id == tenant_id,
                Caller.created_at >= start_of_month,
            )
        )
    ).scalar_one()

    active_users: int = (
        await db.execute(
            select(func.count(User.id)).where(
                User.tenant_id == tenant_id,
                User.status == "active",
            )
        )
    ).scalar_one()

    limit = client.api_limit or 0
    usage_pct = round((total_calls / limit) * 100, 1) if limit else 0.0

    return TenantStats(
        tenant_id=str(tenant_id),
        total_calls=total_calls,
        calls_this_month=calls_this_month,
        active_users=active_users,
        plan_call_limit=limit,
        plan_usage_pct=usage_pct,
    )


# ── Schemas — Audit logs ───────────────────────────────────────────────────────


class AuditLogResponse(BaseModel):
    audit_id: str
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    action: str
    before_value: Optional[dict] = None
    after_value: Optional[dict] = None
    occurred_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PaginatedAuditLogs(BaseModel):
    data: list[AuditLogResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


# ── Audit log endpoints (read-only) ─────────────────────────────────────────────


@router.get("/audit-logs", response_model=PaginatedAuditLogs)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    tenant_id: Optional[int] = Query(None, description="Filter by client/tenant id"),
    action: Optional[str] = Query(None, description="Filter by action, e.g. 'user.update'"),
    db: AsyncSession = Depends(get_tenant_scoped_db),
    user: dict = Depends(_require_admin),
) -> PaginatedAuditLogs:
    stmt = select(AuditLog)

    if user.get("role") == "tenant_admin":
        # Same tenant-isolation pattern as list_users/list_calls: ignore the
        # tenant_id query param, always bind to the JWT's client_id. A
        # tenant_admin never sees platform-level (tenant_id IS NULL) rows.
        jwt_tenant_id = user.get("client_id")
        if not jwt_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="tenant_admin token has no tenant assigned",
            )
        stmt = stmt.where(AuditLog.tenant_id == str(jwt_tenant_id))
    else:
        if tenant_id is not None:
            stmt = stmt.where(AuditLog.tenant_id == str(tenant_id))

    if action:
        stmt = stmt.where(AuditLog.action == action)
    stmt = stmt.order_by(AuditLog.occurred_at.desc())

    total: int = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.offset((page - 1) * per_page).limit(per_page))).scalars().all()

    return PaginatedAuditLogs(
        data=[AuditLogResponse.model_validate(r) for r in rows],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_paginate(total, page, per_page),
    )
