#!/bin/sh
# Staykaro API — container entrypoint.
# NK-02: schema is managed by Alembic, never by hand-editing the database or
# by calling create_all() at app startup (Database Design §9). Migrations run
# here, once, before uvicorn starts serving traffic.
#
# NK-07: `alembic upgrade head` connects using MIGRATION_DATABASE_URL (the
# superuser role — needed for DDL like FORCE ROW LEVEL SECURITY and CREATE
# ROLE), while uvicorn below serves traffic on DATABASE_URL, the restricted
# staykaro_app role RLS actually applies to. These must stay two different
# roles — see .env.example and alembic/versions/df467b3bdd3f_*.py.
set -eu

echo "[entrypoint] Running database migrations..."
alembic upgrade head

echo "[entrypoint] Migrations complete — starting app"
exec "$@"
