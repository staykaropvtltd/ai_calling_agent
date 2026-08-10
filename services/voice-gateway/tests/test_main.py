from fastapi.testclient import TestClient

from main import app, session_manager


def test_health():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_empty_call_lifecycle():
    client = TestClient(app)

    call_id = "test-call-001"

    with client.websocket_connect(f"/ws/{call_id}") as websocket:
        session = session_manager.get(call_id)

        assert session is not None
        assert session.call_id == call_id
        assert session.is_active is True

    assert session_manager.get(call_id) is None