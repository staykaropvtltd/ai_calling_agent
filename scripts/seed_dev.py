#!/usr/bin/env python3
"""Development seed script — creates test clients and users.

ONLY run against a local/development database. Never against production.

Usage (inside the api container):
    docker exec -it staykaro-api python /app/scripts/seed_dev.py

Usage (local Python, pointing at the local Docker postgres):
    DATABASE_URL="postgresql+psycopg://staykaro_user:change_me_in_production@localhost:5433/staykaro" \
    python scripts/seed_dev.py

Accounts created:
  Platform admin (bootstrap login — no DB row, uses API_SECRET_KEY):
    Email:    admin@staykaro.com
    Password: calling_agent_2026

  Client A — Hotel Grand India (INR / Asia/Kolkata / +91):
    admin-india@example.com / DevPassword123!   (tenant_admin)
    user-india@example.com  / DevPassword123!   (agent)

  Client B — Palace Hotel UAE (AED / Asia/Dubai / +971):
    admin-uae@example.com   / DevPassword123!   (tenant_admin)
    user-uae@example.com    / DevPassword123!   (agent)

Run the script again at any time — it is idempotent (skips rows that exist).
"""

import asyncio
import contextlib
import os
import sys

# Allow running from the repo root or from services/api
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "api"))

import bcrypt
from dotenv import load_dotenv
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

_raw_url = (
    os.getenv("DATABASE_URL")
    or os.getenv("MIGRATION_DATABASE_URL")
    or "postgresql+psycopg://staykaro_user:change_me_in_production@localhost:5433/staykaro"
)


# Normalise to asyncpg driver
def _to_asyncpg(url: str) -> str:
    if "+asyncpg" in url:
        return url
    for prefix in (
        "postgresql+psycopg://",
        "postgresql+psycopg2://",
        "postgresql://",
        "postgres://",
    ):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    return url


DATABASE_URL = _to_asyncpg(_raw_url)

_DEV_PASSWORD = "DevPassword123!"


def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


CLIENTS = [
    {
        "name": "Hotel Grand India",
        "slug": "hotel-grand-india",
        "plan": "pro",
        "status": "active",
        "contact_email": "admin@hotelgrandindia.example",
        "contact_phone": "+919876543210",
        "country": "IN",
        "timezone": "Asia/Kolkata",
        "currency": "INR",
        "default_language": "en",
        "phone_country_code": "+91",
        "api_limit": 500,
        "max_concurrent_calls": 20,
        "users": [
            {
                "email": "admin-india@example.com",
                "full_name": "India Admin",
                "role": "tenant_admin",
                "status": "active",
            },
            {
                "email": "user-india@example.com",
                "full_name": "India Reception",
                "role": "agent",
                "status": "active",
            },
        ],
    },
    {
        "name": "Palace Hotel UAE",
        "slug": "palace-hotel-uae",
        "plan": "enterprise",
        "status": "active",
        "contact_email": "admin@palacehoteluae.example",
        "contact_phone": "+97155123456",
        "country": "AE",
        "timezone": "Asia/Dubai",
        "currency": "AED",
        "default_language": "en",
        "phone_country_code": "+971",
        "api_limit": 1000,
        "max_concurrent_calls": 50,
        "users": [
            {
                "email": "admin-uae@example.com",
                "full_name": "UAE Admin",
                "role": "tenant_admin",
                "status": "active",
            },
            {
                "email": "user-uae@example.com",
                "full_name": "UAE Reception",
                "role": "agent",
                "status": "active",
            },
        ],
    },
]


async def seed(db: AsyncSession) -> None:
    # Bypass RLS — seed runs as the superuser role
    with contextlib.suppress(Exception):
        await db.execute(text("SELECT set_config('app.current_tenant', '__all_tenants__', false)"))

    from src.models import Caller, Client, User  # noqa: PLC0415

    pw_hash = _hash(_DEV_PASSWORD)
    created = {"clients": 0, "users": 0}

    for client_def in CLIENTS:
        # Find or create the client
        result = await db.execute(select(Client).where(Client.slug == client_def["slug"]))
        client = result.scalar_one_or_none()

        if client is None:
            client = Client(
                name=client_def["name"],
                slug=client_def["slug"],
                plan=client_def["plan"],
                status=client_def["status"],
                contact_email=client_def["contact_email"],
                contact_phone=client_def["contact_phone"],
                country=client_def.get("country"),
                timezone=client_def.get("timezone"),
                currency=client_def.get("currency"),
                default_language=client_def.get("default_language"),
                phone_country_code=client_def.get("phone_country_code"),
                api_limit=client_def["api_limit"],
                max_concurrent_calls=client_def["max_concurrent_calls"],
            )
            db.add(client)
            await db.flush()  # get id
            created["clients"] += 1
            print(f"  Created client: {client.name} (id={client.id})")
        else:
            # Update i18n fields on existing rows
            client.country = client_def.get("country")
            client.timezone = client_def.get("timezone")
            client.currency = client_def.get("currency")
            client.default_language = client_def.get("default_language")
            client.phone_country_code = client_def.get("phone_country_code")
            print(f"  Client exists: {client.name} (id={client.id}) — i18n fields updated")

        for user_def in client_def["users"]:
            result = await db.execute(select(User).where(User.email == user_def["email"]))
            existing = result.scalar_one_or_none()
            if existing is None:
                u = User(
                    email=user_def["email"],
                    full_name=user_def["full_name"],
                    role=user_def["role"],
                    status=user_def["status"],
                    tenant_id=client.id,
                    password_hash=pw_hash,
                )
                db.add(u)
                created["users"] += 1
                print(f"    Created user: {user_def['email']} ({user_def['role']})")
            else:
                # Ensure password and tenant are always up to date
                existing.password_hash = pw_hash
                existing.tenant_id = client.id
                print(f"    User exists: {user_def['email']} — password reset, tenant confirmed")

        # Seed a few sample calls for this client so the dashboard isn't empty
        call_check = await db.execute(select(Caller).where(Caller.client_id == client.id).limit(1))
        if call_check.scalar_one_or_none() is None:
            sample_calls = [
                Caller(
                    customer_name=f"Sample Guest {i+1}",
                    phone_number=f"{client_def['phone_country_code']}9000000{i:03d}",
                    hotel_name=client_def["name"],
                    check_in_date="2026-09-01",
                    check_out_date="2026-09-03",
                    client_id=client.id,
                )
                for i in range(5)
            ]
            db.add_all(sample_calls)
            print(f"    Seeded 5 sample calls for {client.name}")

    await db.commit()
    print(f"\nDone: {created['clients']} client(s) created, {created['users']} user(s) created.")


async def main() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    print(f"Connecting to: {DATABASE_URL.split('@')[-1]}")
    print("Seeding development data...\n")

    async with async_session() as db:
        await seed(db)

    await engine.dispose()
    print("\nTest accounts:")
    print("  admin@staykaro.com         / calling_agent_2026   (platform super_admin)")
    print("  admin-india@example.com    / DevPassword123!      (tenant_admin — Hotel Grand India)")
    print("  user-india@example.com     / DevPassword123!      (agent — Hotel Grand India)")
    print("  admin-uae@example.com      / DevPassword123!      (tenant_admin — Palace Hotel UAE)")
    print("  user-uae@example.com       / DevPassword123!      (agent — Palace Hotel UAE)")


if __name__ == "__main__":
    asyncio.run(main())
