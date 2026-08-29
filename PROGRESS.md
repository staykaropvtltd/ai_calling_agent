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
| SH-02 | ❌ not started | Twilio adapter — **needs Twilio credentials** to verify against a real sandbox call, even though the adapter code itself doesn't |
| SH-03 | ✅ done (this session) | Pipecat pipeline unified into production entrypoint |
| SH-04/06/08 | ❌ not started | Deepgram STT / Groq LLM / TTS — **need API keys from the user** before this can start. Note: a local/offline fallback pipeline (Whisper + rule-based AI + pyttsx3, see `services/voice-gateway/src/main.py`) already exists and needs no keys — it's what NH-17's draining work below could actually be end-to-end tested against, not attempted this session |
| SH-05/07/09/10/11/12/13/14/15/16/17 | ❌ not started | Depend on SH-04/06/08 |
| NK-05 | ✅ done (this session) | Real DB-backed auth, bcrypt |
| NK-06 | ✅ done (2026-08-29) | `services/api/tests/test_rbac_matrix.py` — exhaustive role × endpoint matrix (90 cases), replacing the old "a couple of tickets check this" coverage |
| NK-07 | ✅ done (this session) | PostgreSQL RLS — see "NK-07 gotchas" below, there were three real bugs |
| NK-08 | ✅ done (2026-08-29) | `services/api/tests/test_tenant_pentest.py` — HTTP-level pen-test suite (18 cases incl. concurrent cross-tenant access); `tests/test_tenant_isolation.py` still separately proves the RLS policies themselves, unchanged |
| NK-09/10/11 | ❌ not started | RAG (ingestion, pgvector retrieval, multilingual embeddings) — needs an embeddings provider (API key or a chosen local model), not attempted this session |
| NK-12/13/14/15 | ❌ not started | Call persistence (blocked on SH-11's turn events), usage metering, Razorpay billing (needs Razorpay keys), webhook idempotency |
| NK-16 | ✅ done (2026-08-29) | Audit logging — `AuditLog` model existed but nothing wrote to it; now wired into every client/tenant/user mutation in `admin.py` (`_write_audit_log`) plus a `GET /admin/audit-logs` read endpoint. Verified live against real Postgres/RLS, not just the SQLite unit suite — see session log |
| NK-17 | ✅ done (2026-08-29) | Backup/restore — continuous WAL archiving (docker-compose.yml's postgres `archive_command`) + `scripts/backup-db.sh` (base backup, `pg_verifybackup`, retention) + `scripts/restore-db.sh` (restores into a disposable scratch container, verifies data). **Actually run** end-to-end against the live stack, not just written — see session log |
| NH-06 | ✅ done | Admin client management — API + `apps/admin-dashboard` UI, built and merged 2026-08-28/29 |
| NH-07 | ❌ not started | Admin live calls/health — blocked on SH-13 (per-stage latency) for the "live calls" half; `/health` already exists for the "health" half but isn't surfaced in a dashboard yet |
| NH-08 | ❌ not started | Admin usage/cost — blocked on NK-13/14 |
| NH-09 | ❌ not started | Client agent config — needs a DB schema for "agent config" this session deliberately didn't invent without a spec (see session log's scoping note) |
| NH-10 | ❌ not started | Client knowledge base — same reason as NH-09, plus depends on NK-09 |
| NH-11 | ⚠️ partial | `apps/client-dashboard`'s Calls list covers the call-log half (2026-08-29); no transcripts (blocked on NK-12/SH-11) or analytics yet |
| NH-12 | ❌ not started | Client billing UI — blocked on NK-14 |
| NH-13/14/15 | ❌ not started | Integration service, email/WhatsApp automation, CRM adapters — see `NH16_N8N_DECISION.md`: recommends building these directly rather than adopting n8n, for both licensing and tenant-isolation reasons |
| NH-16 | ✅ done (2026-08-29) | Written go/no-go decision — see `NH16_N8N_DECISION.md`. Recommendation: **no-go** on self-hosted n8n (likely licensing violation for this use case per n8n's own community guidance, plus weaker tenant isolation than this codebase's RLS-based standard); build automation directly in `services/integration-service` instead |
| NH-17 | ⚠️ partial (2026-08-29) | Deployment draining — mechanism implemented and unit-tested (`voice_pipeline.py` rejects new `/ws/` connections while draining; `src/main.py`'s lifespan shutdown waits for active calls, up to a timeout). NOT verified against a real active call — no live voice pipeline exists yet to generate one (see SH-04/06/08 row) |
| NH-18 | ⚠️ partial (2026-08-29) | Monitoring/alerts — `services/api/src/monitoring.py`: rolling error-rate/latency metrics, DB/Redis-unreachable and disk-usage threshold checks (thresholds transcribed from Infra Guide §5), a periodic evaluation loop, `GET /metrics`. Verified live (forced a real Redis outage, confirmed the alert fired). Deliberately missing: per-stage voice latency and provider-failure-rate metrics (need the live pipeline) and actual paging (Slack/PagerDuty/SMS — needs a destination credential nobody has supplied; logs a structured CRITICAL line instead, see `LoggingNotifier`) |

## Session log

### 2026-08-29 (cont'd) — everything not blocked on external API keys: NK-06/08/16/17, NH-16/17/18

Follow-up to the same day's earlier entry below. Asked to "complete
everything where API is not needed" — audited every open ticket against
the actual Execution Plan PDF (not the earlier informal summary) to
separate what's genuinely blocked on provider credentials from what
isn't, then worked through the latter. Skipped SH-02 (needs Twilio creds
to verify even though the adapter code doesn't strictly), and NH-09/NH-10
(need a DB schema for "agent config"/"knowledge base" this session
deliberately didn't invent without a product spec — flagged, not guessed
at). Everything below was implemented, tested, AND verified against the
live Docker stack (real Postgres with RLS applied, real Redis) — not just
the SQLite unit suite, per this doc's own "how to verify anything" section.

**NK-06 (RBAC role matrix) + NK-08 (tenant isolation pen-test suite).**
Both were "partial" — role checks and cross-tenant checks existed, scattered
across test_admin.py alongside CRUD tests, not as one identifiable suite a
reviewer could point to. Added `test_rbac_matrix.py` (90 cases: every
`/admin/*` route × every role, plus tampered/expired JWT rejection on all of
them) and `test_tenant_pentest.py` (18 cases, modeled directly on Testing
Guide §7's own example cases — cross-tenant ID access, crafted query-param
escalation, cross-tenant mutation attempts, and the one thing nothing else
in the repo covered: concurrent cross-tenant requests via `asyncio.gather`,
proving no per-request state leaks across coroutines).

**NK-16 (audit logging).** The `AuditLog` model/table existed
(`services/api/src/models.py`) with a docstring literally promising it'd be
"written by admin/internal routers whenever a mutating, security-relevant
endpoint is hit" — nothing did. Added `_write_audit_log` (best-effort: never
rolls back the mutation it's describing if the audit write itself fails) and
wired it into every client/tenant/user create/update/delete in `admin.py`,
plus `GET /admin/audit-logs` (tenant-scoped for `tenant_admin`, same pattern
as `list_users`/`list_calls`). One real bug found and fixed along the way:
`create_client`/`update_client`/`delete_client` and the `/admin/tenants`
equivalents used plain `get_db` (no RLS tenant context) — fine for the
unscoped `clients` table itself, but writing to `audit_logs` (which *is*
RLS-scoped) through that session would have hit the exact same RLS rejection
as the earlier `POST /call` bug. Switched all of them to
`get_tenant_scoped_db` (super_admin's cross-tenant sentinel covers it).
Verified live: created/renamed/deleted a real client through the API,
confirmed three correctly-shaped audit rows (before/after diffs, no
`password_hash` ever present) came back from `GET /admin/audit-logs`
against real Postgres.

**NK-17 (backup/restore).** Database Design §10: "a backup nobody has ever
restored doesn't count as a backup," and the ticket's own done-when is
literally "actual restore passes." Added continuous WAL archiving to
postgres's compose config (`archive_mode=on` + `archive_command`, into a new
`postgres_backups` volume — deliberately separate from `postgres_data`),
`scripts/backup-db.sh` (`pg_basebackup` + `pg_verifybackup` + retention
pruning), and `scripts/restore-db.sh` (extracts a base backup into a
disposable scratch Postgres container, replays WAL via `restore_command`,
optionally to a point-in-time target, verifies real row counts, tears
itself down — never touches the running `staykaro-postgres`, so it's safe
to run as a recurring drill). **Actually ran it**, twice — once to catch a
real permission bug (a fresh Docker volume is root-owned; the postgres
process, uid 999, couldn't write into it — fixed with a one-shot
`backups-volume-init` service that chowns it before postgres starts) and a
real shell-quoting bug (building `restore_command`'s value — which itself
contains both `%`-placeholders and single quotes — via string substitution
into an outer double-quoted `bash -c "..."` silently stripped the quotes
and placeholders; fixed by passing it through as an environment variable
into the container's own shell instead of interpolating it as text). Third
run succeeded: full base backup, verified integrity, restored into a
scratch container, confirmed the exact row counts (1 client, 1 admin_user,
1 call_request, 3 audit_logs) matching live state at that moment.

**NH-17 (deployment draining).** Infra Guide §7: the voice gateway should
stop accepting new calls on a shutdown signal and let active ones finish
naturally before the container actually stops. Added an
`is_draining`/`on_call_started`/`on_call_ended` hook set to
`build_voice_router` (`voice_pipeline.py`) — a draining instance closes new
`/ws/{call_id}` connections with code 1013 ("try again later") before
`accept()`, so the telephony platform retries against a different instance
rather than getting a connection that opens and immediately drops.
`src/main.py`'s lifespan shutdown phase sets the flag and polls an
active-call counter down to zero (or a configurable timeout,
`VOICE_GATEWAY_DRAIN_TIMEOUT_SECONDS`, default 300s — a phone call runs
minutes, not the few seconds a typical HTTP graceful-shutdown window
assumes). Mechanism-level unit tests only (8, across two files) — "verified
against a real active call" per the ticket's own done-when needs the live
voice pipeline, which doesn't exist yet (SH-04/06/08 blocked on provider
keys). Worth knowing for later: `services/voice-gateway/src/main.py`
already has a fully local, no-API-key fallback pipeline (Whisper + a
rule-based responder + pyttsx3) mentioned in its own comments as existing
for exactly this kind of dev/test purpose — that's the actual path to
closing NH-17's real-call verification without waiting on any provider
key, just wasn't attempted this session (scope was already large).

**NH-18 (monitoring/alerts).** Full scope needs per-stage voice latency and
provider failure rate (blocked) and real paging — Slack/PagerDuty/SMS all
need a destination credential nobody has supplied. Built what's actually
available: `services/api/src/monitoring.py` — a rolling-window metrics
registry (error rate, p50/p95 latency), threshold evaluation transcribed
directly from Infra Guide §5's table (error rate, latency, DB/Redis
unreachable, disk usage), and a `Notifier` Protocol whose only shipped
implementation is a structured `logger.critical("ALERT ...")` line —
deliberately the seam a real destination gets wired into later, not a
guess at what that destination should be. A periodic loop (default 60s,
`MONITORING_INTERVAL_SECONDS`) evaluates independently of request traffic,
so a threshold like "elevated error rate for 5 minutes" fires even during
a quiet period. `GET /metrics` (super_admin-only) exposes the current
snapshot on demand. Verified live: stopped the real `staykaro-redis`
container for ~15s with the interval turned down to 5s for the test, and
watched the exact expected `ALERT [redis_unreachable]` and
`ALERT [latency_p95]` lines appear in the API's logs — not inferred from
reading the code, actually triggered.

**NH-16 (n8n licensing/isolation decision).** Written recommendation in
`NH16_N8N_DECISION.md`: **no-go** on self-hosted n8n for NH-13/14/15's
automation. Researched n8n's own Sustainable Use License docs and — more
usefully — a community-forum thread where n8n's own moderators answered
almost this exact question (SaaS company, n8n hidden entirely behind their
own product) for another company: the deciding factor isn't whether
customers see n8n's UI, it's whether they derive value from its automation
even indirectly, which very likely puts Staykaro's use case outside the
free license and into paid Enterprise territory. Independent of licensing,
n8n Community Edition also has no native multi-tenant RBAC — a fail-open
isolation story (a workflow that forgets to scope by tenant just silently
touches the wrong tenant's data), the opposite of this codebase's own
RLS-based fail-closed standard that NK-07/NK-08 spent real effort proving
out. Recommendation: build NH-13/14/15's automation directly in
`services/integration-service` instead — same tenant-isolation guarantees
as the rest of the API, no licensing question to resolve first. Full
reasoning and sources in the decision doc; this is a recommendation for a
human to sign off on, not a unilateral decision.

**Verification note:** every ticket above that touches Postgres was run
against the actual live `docker compose --profile all` stack, not only the
SQLite unit suite — rebuilding the `api` container after each backend
change and hitting it with real `curl`/`docker exec` commands, exactly this
doc's own "always verify Docker changes by actually building and running
the image" instruction. Full backend suite (`services/api/tests/` +
`tests/` + `app/tests/` + `services/worker/tests/` +
`services/integration-service/tests/`) sits at 413 passed, 24 skipped (the
real-Postgres RLS suite, which needs `TEST_POSTGRES_DSN` env vars this
session's ad hoc verification didn't set up) as of this entry.

### 2026-08-29 — merge Phase 7 admin-dashboard, build client-dashboard, fix POST /call RLS bug

Three things, in order: pulled the latest `origin/main` into
`feature/admin-dashboard`, built a second frontend for tenant-facing users,
and fixed a real backend bug the new frontend's error handling surfaced
immediately once run against a live stack.

**Merge.** `origin/main` had picked up two commits this branch didn't:
`dc85443` (PR #24, a squash-merge of this same branch's earlier
admin-dashboard commits) and `1596476` (PR #25, stabilization fixes on top).
Because #24 was a squash merge, git saw it as unrelated history to this
branch's own un-squashed commits touching the same files — 5 add/add
conflicts, all in `apps/admin-dashboard`, all resolved in favor of main's
newer logic: FastAPI 422 validation-array handling in `ErrorBanner`, the
"New user" button gated behind `isSuperAdmin`, the tenant `<select>`
populated from `useTenantsQuery` instead of a bare text input, nullable
`contact_email`/`max_concurrent_calls` defaults matching the relaxed
`TenantResponse` schema, and `/admin/login/` with the trailing slash
`next.config.js`'s `trailingSlash: true` now requires. Verified with
`typecheck`/`lint`/`test`/`build` post-merge — all green.

**`apps/client-dashboard`.** Tenant-facing counterpart to admin-dashboard,
for `tenant_admin`/`agent` (not `super_admin`, who gets "access denied" and
is pointed at `/admin/` instead — same-origin `sessionStorage` means one
login serves both apps, confirmed by hand). Mirrors admin-dashboard's stack
(Next.js 16, React Query, Tailwind, vitest) but scoped down to what those
two roles can actually do server-side: **New call** (`POST /call`, open to
any authenticated role) plus, `tenant_admin`-only, read-only **Calls** and
**Users** lists (`/admin/calls`, `/admin/users` — already tenant-scoped by
`_require_admin`). No tenant or user management — those routes are
`super_admin`-only, so the UI never offers what the API would 403. Wired
into `docker-compose.yml` (port 3001, profile `all`), nginx dev/prod
(`/client/` path routing, same redirect-loop-avoidance pattern as
`/admin/`), CI (new `frontend-client` job + docker build validation), and
`.env` templates.

**Bug found and fixed: `POST /call` 500'd for every real (non-bootstrap)
user.** Caught by running the actual stack (`docker compose --profile all
up`, real Postgres with NK-07's RLS migration applied) and driving the new
New Call form in a browser — not by any unit test, since the SQLite suite
has no RLS to enforce this. Root cause: `make_call` in
`services/api/src/main.py` used plain `get_db` (no `app.current_tenant`
session context) and never set `client_id` on the `Caller` row it inserts.
`call_requests`' `tenant_isolation` policy's `WITH CHECK` requires
`client_id::text = current_setting('app.current_tenant')`, which a NULL
`client_id` under an unset (empty-string) tenant context never satisfies —
confirmed by reproducing with a direct `curl` against the API, independent
of the frontend, and by reading `staykaro-api`'s logs
(`asyncpg.exceptions.InsufficientPrivilegeError: new row violates row-level
security policy for table "call_requests"`). Fix: switched the dependency to
`get_tenant_scoped_db` (sets that session context from the caller's JWT —
the cross-tenant sentinel for `super_admin`) and set
`client_id=user.get("client_id")` explicitly, which is `None` for
`super_admin` (fine — the sentinel bypasses the check) and the caller's own
tenant id otherwise (satisfies it). Added `services/api/tests/test_call.py`
— it can't reproduce the RLS rejection itself (no RLS in SQLite) but does
guard the actual fix, that `client_id` gets stamped from the token for
`tenant_admin`/`agent` and stays `None` for `super_admin`. Full backend
suite (148 tests) and both frontends' suites (17 + 16 tests) pass; verified
live end-to-end afterward — `curl`'d `/call` against the rebuilt API
container and confirmed the row landed with the right `client_id` in
Postgres.

**Non-obvious thing worth knowing:** nginx and the API bake their config/
code into the image at build time (`COPY`, not a bind mount, in dev) — a
`docker compose up -d` alone after editing `nginx.conf` or `src/main.py`
restarts the *old* image. Needs `up -d --build <service>` (confirmed by
hand: the first `up -d` after adding `client-dashboard` brought back
25-hour-old containers with none of this session's nginx/api changes in
them).

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
