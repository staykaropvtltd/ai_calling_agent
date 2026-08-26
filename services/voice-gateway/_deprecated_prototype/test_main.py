from fastapi.testclient import TestClient

from app.services.redis_service import get_call_session
from main import app, session_manager


def test_health():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_call_lifecycle_redis():
    client = TestClient(app)

    call_id = "test-call-001"

    # WebSocket connect → session should be created
    with client.websocket_connect(f"/ws/{call_id}"):
        session = session_manager.get(call_id)

        # In-memory session exists
        assert session is not None
        assert session.call_id == call_id
        assert session.is_active is True

        # Redis session exists
        redis_session = get_call_session(call_id)

        assert redis_session is not None
        assert redis_session["call_id"] == call_id
        assert redis_session["status"] == "active"

    # WebSocket disconnect → Redis session should be removed
    assert session_manager.get(call_id) is None
    assert get_call_session(call_id) is None
