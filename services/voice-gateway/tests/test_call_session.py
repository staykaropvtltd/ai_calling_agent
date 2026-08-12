import pytest

from app.services.redis_service import delete_call_session
from call_session import CallSessionManager


@pytest.fixture(autouse=True)
def cleanup_test_sessions():
    test_call_ids = [
        "call_001",
        "call_002",
        "call_003",
        "call_004",
    ]

    for call_id in test_call_ids:
        delete_call_session(call_id)

    yield

    for call_id in test_call_ids:
        delete_call_session(call_id)


def test_create_and_get_session():
    manager = CallSessionManager()

    session = manager.create(
        call_id="call_001",
        tenant_id="tenant_001",
        agent_id="agent_001",
    )

    assert session.call_id == "call_001"
    assert session.tenant_id == "tenant_001"
    assert session.agent_id == "agent_001"
    assert session.is_active is True

    fetched = manager.get("call_001")

    assert fetched is session


def test_end_session():
    manager = CallSessionManager()

    manager.create(
        call_id="call_002",
        tenant_id="tenant_001",
        agent_id="agent_001",
    )

    session = manager.end("call_002")

    assert session.is_active is False
    assert session.ended_at is not None


def test_remove_session():
    manager = CallSessionManager()

    manager.create(
        call_id="call_003",
        tenant_id="tenant_001",
        agent_id="agent_001",
    )

    removed = manager.remove("call_003")

    assert removed is not None
    assert manager.get("call_003") is None


def test_duplicate_call_id_rejected():
    manager = CallSessionManager()

    manager.create(
        call_id="call_004",
        tenant_id="tenant_001",
        agent_id="agent_001",
    )

    with pytest.raises(ValueError):
        manager.create(
            call_id="call_004",
            tenant_id="tenant_001",
            agent_id="agent_001",
        )