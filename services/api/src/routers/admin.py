import logging
import math
from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user
from src.database import get_db
from src.models import Caller, Client, User

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


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    role: Optional[str]
    tenant_id: Optional[int]
    status: Optional[str]
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


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


# ── Client endpoints ──────────────────────────────────────────────────────────


@router.post("/clients", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
async def create_client(
    body: ClientCreate,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_require_super_admin),
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
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_require_super_admin),
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

    for field, value in updates.items():
        setattr(client, field, value)
    await db.commit()
    await db.refresh(client)
    return client


@router.delete("/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: int,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_require_super_admin),
) -> None:
    """Soft delete — sets status to 'inactive'. Data is retained."""
    client = await db.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    client.status = "inactive"
    await db.commit()
    logger.info("Client soft-deleted: id=%s", client_id)


@router.get("/clients/{client_id}/stats", response_model=ClientStats)
async def get_client_stats(
    client_id: int,
    db: AsyncSession = Depends(get_db),
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
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_require_super_admin),
) -> User:
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

    user = User(**body.model_dump())
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info("User created: id=%s email=%s role=%s", user.id, user.email, user.role)
    return user


@router.get("/users", response_model=PaginatedUsers)
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    tenant_id: Optional[int] = Query(None),
    role: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_require_super_admin),
) -> PaginatedUsers:
    stmt = select(User)
    if tenant_id is not None:
        stmt = stmt.where(User.tenant_id == tenant_id)
    if role:
        stmt = stmt.where(User.role == role)
    if status_filter:
        stmt = stmt.where(User.status == status_filter)

    total: int = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.offset((page - 1) * per_page).limit(per_page))).scalars().all()

    return PaginatedUsers(
        data=list(rows),
        total=total,
        page=page,
        per_page=per_page,
        total_pages=_paginate(total, page, per_page),
    )


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_require_super_admin),
) -> User:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_require_super_admin),
) -> User:
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

    for field, value in updates.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_require_super_admin),
) -> None:
    """Soft delete — sets status to 'suspended'. Data is retained."""
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.status = "suspended"
    await db.commit()
    logger.info("User soft-deleted (suspended): id=%s", user_id)


# ── Call log endpoints (read-only) ────────────────────────────────────────────


@router.get("/calls", response_model=PaginatedCalls)
async def list_calls(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    tenant_id: Optional[int] = Query(None, description="Filter by client/tenant id"),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_require_super_admin),
) -> PaginatedCalls:
    stmt = select(Caller)
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
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_require_super_admin),
) -> Caller:
    call = await db.get(Caller, call_id)
    if not call:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    return call
