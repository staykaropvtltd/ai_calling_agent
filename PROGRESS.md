# Staykaro AI Caller — Progress Log

Living document. Read this first, before re-reading the codebase or the six
technical PDFs — it exists so a new session doesn't have to rediscover
context that's already been figured out. Update it whenever you close out
a ticket or make a decision worth remembering; keep entries terse and
append newest-first within each section.

For the full ticket list, ownership, and phase plan, see
`Staykaro_Team_Execution_Plan_V1.1_Compact_v3_Readable.pdf` — this file
only tracks *actual* status against that plan, which the plan PDF and
README's ticket table do not track live.

## How to verify anything in this repo

Real Postgres (pgvector) + Redis are expected via `docker compose up -d
postgres redis` — don't assume SQLite-only. The unit test suite
(`app/tests/`, `services/api/tests/`) runs against in-memory SQLite via
`services/api/tests/conftest.py` and needs no real DB. RLS/tenant tests
(`tests/test_tenant_isolation.py`) need real Postgres and skip cleanly if
it's unreachable — see that file's docstring for the exact setup commands
(migrate with `MIGRATION_DATABASE_URL` + `APP_DB_PASSWORD` set first).

```bash
# fast unit suite (SQLite, no real DB needed)
export REDIS_URL=redis://localhost:6380/0 DATABASE_URL=postgresql+psycopg://ci:ci@localhost:5432/ci \
       SUPABASE_DB_URL=postgresql+asyncpg://ci:ci@localhost:5432/ci BLAND_API_KEY=dummy
python -m pytest app/tests/ services/api/tests/ tests/ -q

# lint / security (matches CI exactly)
python -m ruff check app/ services/
python -m bandit -r services/api/src -ll -q
```

Always verify Docker changes by actually building and running the image
against real Postgres/Redis — the SQLite unit suite does not catch
container-level or RLS-level bugs (see the two real bugs found this way,
below). `docker build -t <name> ./services/<x>` then `docker run` on
`staykaro-network` alongside the existing `staykaro-postgres`/
`staykaro-redis` containers.

## Status against the plan (as of 2026-08-26)

**CP1 (foundation: stack + health + empty call lifecycle) — met.**
Phase 0 is fully done. Phase 4 (multi-tenancy, the plan's hard gate) is
partially done *ahead* of the plan's own sequencing — NK-05 and NK-07 are
in, NK-06/NK-08 are not.

| Ticket | Status | Notes |
|---|---|---|
| NH-01–05 | ✅ done | Docker Compose, Dockerfiles, Nginx, CI/CD, deploy scripts |
| NK-01 | ✅ done | FastAPI skeleton |
| NK-02 | ✅ done (this session) | Alembic migrations replace `create_all()` |
| NK-03 | ✅ done | Redis call sessions |
| NK-04 | ✅ done | Health/readiness |
| SH-01 | ✅ done | Exotel adapter |
| SH-02 | ❌ not started | Twilio adapter |
| SH-03 | ✅ done (this session) | Pipecat pipeline unified into production entrypoint |
| SH-04/06/08 | ❌ not started | Deepgram STT / Groq LLM / TTS — **need API keys from the user** before this can start |
| SH-05/07/09/10/11/12/13/14/15/16/17 | ❌ not started | Depend on SH-04/06/08 |
| NK-05 | ✅ done (this session) | Real DB-backed auth, bcrypt |
| NK-06 | ⚠️ partial | Role-check dependencies exist (`_require_admin`/`_require_super_admin`); no formal role/permission matrix beyond that |
| NK-07 | ✅ done (this session) | PostgreSQL RLS — see "NK-07 gotchas" below, there were three real bugs |
| NK-08 | ⚠️ partial | `tests/test_tenant_isolation.py` covers the DB layer directly; no HTTP-level pen-test suite yet |
| NK-09–17 | ❌ not started | RAG, billing, audit logging (table exists, nothing writes to it yet), backup/restore |
| NH-06 | ⚠️ partial | Admin API (clients/users/calls CRUD) done; no dashboard UI |
| NH-07–18 | ❌ not started | Dashboards, integrations, monitoring, hardening |

## Session log

### 2026-08-26 — NK-02, SH-03, NK-05, NK-07 (this session)

Worked in priority order: close CP1 first (NK-02 + SH-03), then NK-05,
then NK-07 (the plan's explicit hard gate). Full detail in commit
`d6a6f20`. Three non-obvious things worth knowing before touching this
code again:

**NK-07 / RLS — `staykaro_user` is a Postgres superuser.** The
`POSTGRES_USER` bootstrap account created by the official postgres image
is *always* a superuser, and superusers unconditionally bypass RLS —
`FORCE ROW LEVEL SECURITY` does not override this, there is no flag that
does. Confirmed by hand: policies existed, were enabled, and restricted
nothing until this was fixed. Fix: a second role, `staykaro_app`
(`NOSUPERUSER NOBYPASSRLS`), created by the migration
(`services/api/alembic/versions/df467b3bdd3f_*.py`), which the API
actually connects as (`DATABASE_URL`). `staykaro_user` is now
migrations-only, via `MIGRATION_DATABASE_URL`. **If you add a new
Postgres-backed service, it must connect as `staykaro_app`, not
`staykaro_user`, or its queries silently bypass RLS.**

**NK-07 / RLS — fail closed, not fail open.** The policies use an
explicit `__all_tenants__` sentinel (`src/tenant.py`) for cross-tenant
access, not "unset = unrestricted". A route that forgets to wire
`get_tenant_scoped_db` (or `get_internal_service_db` for
non-JWT/service-to-service routes) sees **zero rows**, not every tenant's
rows. If you add a new endpoint that queries `admin_users`, `call_requests`,
`calls`, `call_turns`, `call_events`, or `audit_logs`, it needs one of
those two dependencies in place of plain `get_db`, or it will look broken
(empty results) — that's the intended failure mode, not a bug to route
around by switching back to `get_db`.

**NK-07 / RLS — session-scoped, not `SET LOCAL`.** The Database Design
PDF's illustrative example uses `SET LOCAL` (transaction-scoped). That
breaks in this codebase because `routers/admin.py` routinely does
`add() → commit() → refresh()` inside one handler — `SET LOCAL` resets the
instant that first `commit()` happens, so `refresh()` runs with no tenant
context and fails closed to nothing (this was hit and debugged live, not
theoretical). Fixed with session-scoped `set_config(..., false)` plus an
explicit `RESET app.current_tenant` in `get_db()`'s `finally` block, so
context can't leak to the next request on a recycled pooled connection
either. `src/tenant.py` and `src/database.py` both have long comments
explaining this — read them before changing either.

**SH-03 — the old prototype was never actually deployed.** Root
`services/voice-gateway/main.py` had a working Pipecat pipeline, but the
Dockerfile only ever copied `src/`, `exotel_routes.py`, `internal_calls.py`,
and `dev_routing.py` — the prototype was dead code with passing tests that
never proved anything about the real container. Moved to
`_deprecated_prototype/` (not deleted — no prior git history in this repo
to recover from if that turned out to be wrong). The real pipeline now
lives in `services/voice-gateway/voice_pipeline.py`, wired into
`src/main.py`. It also had a live bug TestClient-based tests didn't catch:
no `on_client_disconnected` handler, so the pipeline never stopped and the
Redis session key never got cleaned up on a real hangup — only found by
running the built image against a real container and checking Redis by
hand.

**Scope decisions made, not just bugs:**
- RAG/billing/RLS scope: RLS covers `call_requests` and `admin_users`
  (what's actually queried today) plus `calls`/`call_turns`/`call_events`/
  `audit_logs` (schema-only, ahead of SH-11/NK-12/NK-16) — not `clients`
  or `phone_number_routes` (not per-tenant rows themselves; `clients`
  management is already super_admin-only at the app layer).
- Kept `Client.id` as `Integer`, not a rewrite to UUID tenant IDs matching
  the Database Design PDF's schema literally — the existing Integer-keyed
  model is already used pervasively and tested; RLS doesn't require UUID
  (compares as text either way). Revisit only if/when the doc's full
  `tenants`/`agents`/`agent_languages` schema actually gets built out for
  RAG or multilingual work.
- `worker`/`integration-service` were left on plain `DATABASE_URL`
  (now the restricted role) — they're bare stubs today with no real
  queries, so this is forward-compatible, not yet exercised.

### Repo/branching note

This working directory was a downloaded ZIP snapshot of `origin/main`
(no `.git` present), not a clone — first push from here required `git
init` + `git remote add` + a manual merge with `--allow-unrelated-histories`
against the real `origin/main` history. That's a one-time thing; from the
pushed branch onward, normal clone/branch/PR workflow applies.
