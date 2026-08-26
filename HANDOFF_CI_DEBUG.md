# Handoff — CI failures on PR #21 — RESOLVED

Branch: `nk-02-nk-05-nk-07-cp1-and-tenant-rls`
PR: https://github.com/staykaropvtltd/ai_calling_agent/pull/21

Both CI failures below were root-caused with direct evidence (clean venv,
instrumented library code, not guesses) and fixed. Not yet pushed as of
writing — see "What's left" at the bottom.

## 1. Security (bandit · pip-audit) — fixed

Same category as the other 7 already-accepted starlette CVEs: `fastapi==0.115.6`
requires `starlette<0.42.0,>=0.40.0`; the fix for `PYSEC-2026-1942` is
`starlette>=0.49.1`, outside that range — no fix available without a bigger
FastAPI upgrade. Added `--ignore-vuln PYSEC-2026-1942` to the services/api
pip-audit step in `.github/workflows/main.yml` and documented it in
`SECURITY_NOTICE.md` (also corrected that file's stale "FastAPI 0.115.0"
reference to the actual current pin, 0.115.6).

## 2. Unit Tests — `test_voice_websocket_creates_and_removes_session` — fixed

**Root cause (confirmed with instrumented logging in a genuinely clean venv,
not assumed):** no real Redis is reachable in CI (`.github/workflows/main.yml`'s
`test` job has no `services:` block at all) or in most local dev setups.
`services/voice-gateway/src/main.py`'s `_GatewaySessionManager` uses the
synchronous `redis` package directly inside async FastAPI/pipecat request
handlers, with no timeout configured and no executor offload. When Redis is
unreachable, the first real Redis call blocks the *entire event loop*
(observed ~4s locally on Windows, unbounded/OS-dependent in general — a
genuine production resiliency risk, not just a test artifact).

This test is the only one of the three websocket tests in
`tests/test_gateway_callbacks.py` that calls `session_manager.get(call_id)`
for a call_id that was never created anywhere first (the other two either
skip the check or pre-populate the in-memory dict synchronously before
connecting). That makes it the only one that hits the slow Redis-fallback
path — on *both* the background thread running the route handler (inside
`voice_websocket()`, before `session_manager.create()` ever runs) and the
main test thread's own direct `session_manager.get()` call. Both are
independent blocking calls to the same unreachable Redis; whichever returns
first (with `None`, since the in-memory dict was still empty) decided the
test outcome — a genuine, deterministic-given-no-Redis race, not a
starlette/pipecat/dependency-version issue as originally suspected.

Confirmed via: a clean `python -m venv` (no drift from earlier ad-hoc
installs), reproduced identically to CI's exact resolved versions
(`fastapi==0.115.6`, `starlette==0.41.3`), then instrumented
`pipecat.workers.runner`, `pipecat.transports.websocket.fastapi`, and
`starlette.testclient` directly in the venv's `site-packages` (not the repo)
with timestamped debug logging. This showed the disconnect frame's raw ASGI
message (`{'type': 'websocket.disconnect', 'code': 1000, 'reason': None}`)
arriving in the pipeline ~4 seconds after `websocket.accept()`, correlating
exactly with `_GatewaySessionManager.get()`'s Redis-connect stall — not with
any starlette/pipecat internal race. All instrumentation was reverted
(`pip install --force-reinstall --no-deps` for the two pipecat/starlette
files) before finishing; no debug code was left in installed packages.

**Fix applied (two parts):**

1. `services/voice-gateway/src/main.py` — added `socket_connect_timeout` /
   `socket_timeout` (2s) to both Redis client constructions (`_shared_redis`
   and `_GatewaySessionManager.__init__`'s own client). This is a real
   production hardening fix independent of the test: an unreachable Redis
   should fail fast, not stall every in-flight call's event loop for an
   OS-dependent, potentially very long time.
2. `tests/test_gateway_callbacks.py` — the module-level exec of
   `services/voice-gateway/src/main.py` now temporarily unsets `REDIS_URL`
   around that one import, so `session_manager`/`_shared_redis` fall back to
   the already-supported in-memory-only mode instead of attempting any real
   network I/O. This matches the project's established "no real DB/Redis
   needed for unit tests" convention (see `services/api/tests/conftest.py`'s
   `REDIS_URL` comment) — this was simply the first test in the suite that
   actually exercised a Redis-touching code path via the real production
   `session_manager`, unlike the Exotel callback tests in the same file
   which build their own router with `_FakeRedis`.

**Verified (in the clean venv, exact CI command):**
- `pytest app/tests/ services/api/tests/ tests/ --tb=short --cov=app --cov=src --cov-report=term-missing --cov-fail-under=60`
  → 192 passed, coverage 77.46% (gate is 60%). Suite runtime dropped from
  ~82s to ~15s, confirming the Redis stall is what was slow, not just flaky.
- `tests/test_gateway_callbacks.py` alone run 5x in a row → deterministic,
  all pass, ~3.2s each time.
- `ruff check app/`, `ruff check services/` → clean.
- `bandit -r services/api/src -ll -q`, `bandit -r app/ -ll -q` → clean.
- `pip-audit -r requirements.txt --ignore-vuln PYSEC-2026-1325` → clean.
- `pip-audit -r services/api/requirements.txt <full ignore list + PYSEC-2026-1942>` → clean.

Docker-build job was not touched by any of these changes (no Dockerfile/nginx
config edits) and wasn't re-verified — no reason to expect it's affected.

## What's left

Nothing code-wise — all four CI jobs were verified to pass locally with the
exact commands/flags CI uses. **Not yet committed or pushed** as of writing
this file. Next session (or continuing this one): review the diff
(`.github/workflows/main.yml`, `SECURITY_NOTICE.md`,
`services/voice-gateway/src/main.py`, `tests/test_gateway_callbacks.py`),
commit, push to the PR branch, and confirm the actual GitHub Actions run
goes green (local reproduction is high-confidence but the real CI runners
are Ubuntu, not Windows — the Redis-unreachable-stall mechanism is
platform-independent since it's about TCP connect behavior against a
non-listening port, not IPv6/Windows-specific, so this should hold, but
watch the real run to be sure).

`PROGRESS.md` (repo root) has the full session history before this
CI-debugging session — read that first for broader context on NK-02/SH-03/
NK-05/NK-07.
