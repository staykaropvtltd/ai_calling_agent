# Deprecated — superseded by `src/main.py`

`main.py` and `call_session.py` were the original SH-03 prototype: a bare
Pipecat pipeline with its own `CallSessionManager`, coupled to the legacy
`app/` package's Redis service. They were never part of the Docker image
(`services/voice-gateway/Dockerfile` only ever copied `src/`) and never ran
in any deployed environment — the callback-handling app in `src/main.py` had
no voice/WebSocket path at all.

As of the SH-03 unification, `src/main.py` + `src/voice_pipeline.py` own the
full path: Exotel callback → session created → `/ws/{call_id}` audio stream
→ session cleaned up, all sharing one `session_manager`. This directory is
kept only for history; it is not imported by anything and not built into any
image. Safe to delete once nobody needs the diff for reference.

Their test coverage was carried forward as new tests in
`tests/test_gateway_callbacks.py` (`test_voice_websocket_*`), which exercise
the real `src/main.py` app instead of this prototype.
