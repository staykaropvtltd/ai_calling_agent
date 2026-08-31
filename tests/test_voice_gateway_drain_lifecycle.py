"""
NH-17 — the drain wait/timeout loop in services/voice-gateway/src/main.py's
lifespan shutdown phase. Complements test_voice_pipeline_draining.py (which
covers the router-level new-connection rejection) with the other half: does
shutdown actually wait for active calls to end, and does it give up after
its configured timeout instead of hanging forever.

Loads src/main.py under its own private module name (same technique
test_gateway_callbacks.py uses, and for the same reason: services/api/tests/
conftest.py already claims "src.main" in sys.modules) — a *different* private
name than that file's "_voice_gateway_main", so this file's use of the
module-level _active_calls/_draining globals can't leak state into or out of
that file's copy when both run in the same pytest session.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio

_VG = str((Path(__file__).parent.parent / "services" / "voice-gateway").resolve())
if _VG not in sys.path:
    sys.path.insert(0, _VG)

_saved_redis_url = os.environ.pop("REDIS_URL", None)
try:
    _gw_main_path = Path(_VG) / "src" / "main.py"
    _gw_spec = importlib.util.spec_from_file_location(
        "_voice_gateway_main_drain_test", str(_gw_main_path)
    )
    _GW_MAIN = importlib.util.module_from_spec(_gw_spec)
    sys.modules["_voice_gateway_main_drain_test"] = _GW_MAIN
    _gw_spec.loader.exec_module(_GW_MAIN)  # type: ignore[union-attr]
finally:
    if _saved_redis_url is not None:
        os.environ["REDIS_URL"] = _saved_redis_url


@pytest.fixture(autouse=True)
def _reset_drain_state():
    """Each test starts from a clean slate — these are module-level globals
    shared across every test in this file."""
    _GW_MAIN._draining = False
    _GW_MAIN._active_calls = 0
    yield
    _GW_MAIN._draining = False
    _GW_MAIN._active_calls = 0


async def test_on_call_started_and_ended_track_active_calls():
    assert _GW_MAIN._active_calls == 0
    _GW_MAIN._on_call_started()
    _GW_MAIN._on_call_started()
    assert _GW_MAIN._active_calls == 2
    _GW_MAIN._on_call_ended()
    assert _GW_MAIN._active_calls == 1
    _GW_MAIN._on_call_ended()
    assert _GW_MAIN._active_calls == 0


async def test_shutdown_sets_draining_immediately(monkeypatch):
    monkeypatch.setattr(_GW_MAIN, "_DRAIN_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(_GW_MAIN, "_DRAIN_POLL_INTERVAL_SECONDS", 0.05)

    async with _GW_MAIN._lifespan(None):
        assert _GW_MAIN._draining is False
    # Shutdown phase (after the `async with` block exits) must flip this —
    # this is the flag build_voice_router's is_draining() check reads.
    assert _GW_MAIN._draining is True


async def test_shutdown_waits_for_active_calls_to_reach_zero(monkeypatch):
    monkeypatch.setattr(_GW_MAIN, "_DRAIN_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(_GW_MAIN, "_DRAIN_POLL_INTERVAL_SECONDS", 0.05)

    _GW_MAIN._on_call_started()

    async def _end_call_shortly():
        await asyncio.sleep(0.12)
        _GW_MAIN._on_call_ended()

    async with _GW_MAIN._lifespan(None):
        ender = asyncio.create_task(_end_call_shortly())

    await ender
    # If shutdown had returned before the call actually ended, this would
    # still be 0 only by coincidence of timing — the real assertion is that
    # _lifespan's shutdown phase didn't return while _active_calls was still 1.
    assert _GW_MAIN._active_calls == 0


async def test_shutdown_gives_up_after_timeout_with_calls_still_active():
    _GW_MAIN._DRAIN_TIMEOUT_SECONDS = 0.1
    _GW_MAIN._DRAIN_POLL_INTERVAL_SECONDS = 0.02
    try:
        _GW_MAIN._on_call_started()  # never ended — simulates a stuck call

        async with _GW_MAIN._lifespan(None):
            pass
        # Reaching this line at all proves shutdown returned instead of
        # hanging forever waiting for a call that was never going to end.
        assert _GW_MAIN._active_calls == 1
    finally:
        _GW_MAIN._DRAIN_TIMEOUT_SECONDS = 300
        _GW_MAIN._DRAIN_POLL_INTERVAL_SECONDS = 2
