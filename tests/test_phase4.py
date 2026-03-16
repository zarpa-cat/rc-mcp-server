"""Tests for Phase 4: webhook event queue.

Covers:
- EventQueue: store_event, query_events, get_stats, purge_old_events
- MCP tools: rc_get_recent_events, rc_queue_status
- Webhook server: POST /webhooks/revenuecat, GET /health, GET /stats
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from rc_mcp_server.event_queue import EventQueue

# ── EventQueue unit tests ─────────────────────────────────────────────────────


@pytest.fixture()
def tmp_queue(tmp_path: Path) -> EventQueue:
    return EventQueue(db_path=tmp_path / "test_events.db")


def test_store_and_query_basic(tmp_queue: EventQueue) -> None:
    row_id = tmp_queue.store_event(
        event_type="BILLING_ISSUE",
        app_user_id="user_001",
        payload={"type": "BILLING_ISSUE", "app_user_id": "user_001"},
    )
    assert isinstance(row_id, int)
    assert row_id > 0

    events = tmp_queue.query_events()
    assert len(events) == 1
    assert events[0].event_type == "BILLING_ISSUE"
    assert events[0].app_user_id == "user_001"


def test_queued_event_to_dict(tmp_queue: EventQueue) -> None:
    tmp_queue.store_event("RENEWAL", "user_abc", {"type": "RENEWAL"})
    events = tmp_queue.query_events()
    d = events[0].to_dict()

    assert d["event_type"] == "RENEWAL"
    assert d["app_user_id"] == "user_abc"
    assert "age_seconds" in d
    assert "payload" in d
    assert isinstance(d["payload"], dict)


def test_filter_by_user(tmp_queue: EventQueue) -> None:
    tmp_queue.store_event("RENEWAL", "alice", {"type": "RENEWAL"})
    tmp_queue.store_event("CANCELLATION", "bob", {"type": "CANCELLATION"})

    alice_events = tmp_queue.query_events(app_user_id="alice")
    assert len(alice_events) == 1
    assert alice_events[0].app_user_id == "alice"

    bob_events = tmp_queue.query_events(app_user_id="bob")
    assert len(bob_events) == 1
    assert bob_events[0].event_type == "CANCELLATION"


def test_filter_by_event_type(tmp_queue: EventQueue) -> None:
    tmp_queue.store_event("RENEWAL", "user_1", {})
    tmp_queue.store_event("BILLING_ISSUE", "user_1", {})
    tmp_queue.store_event("BILLING_ISSUE", "user_2", {})

    billing_events = tmp_queue.query_events(event_type="BILLING_ISSUE")
    assert len(billing_events) == 2

    renewal_events = tmp_queue.query_events(event_type="RENEWAL")
    assert len(renewal_events) == 1


def test_event_type_case_insensitive(tmp_queue: EventQueue) -> None:
    tmp_queue.store_event("CANCELLATION", "user_x", {})
    # Query with lower case — should match due to .upper() in query_events
    events = tmp_queue.query_events(event_type="cancellation")
    assert len(events) == 1


def test_filter_combined(tmp_queue: EventQueue) -> None:
    tmp_queue.store_event("BILLING_ISSUE", "alice", {})
    tmp_queue.store_event("BILLING_ISSUE", "bob", {})
    tmp_queue.store_event("RENEWAL", "alice", {})

    events = tmp_queue.query_events(app_user_id="alice", event_type="BILLING_ISSUE")
    assert len(events) == 1
    assert events[0].app_user_id == "alice"
    assert events[0].event_type == "BILLING_ISSUE"


def test_limit(tmp_queue: EventQueue) -> None:
    for i in range(10):
        tmp_queue.store_event("TEST", f"user_{i}", {"index": i})

    events = tmp_queue.query_events(limit=5)
    assert len(events) == 5


def test_since_hours_filter(
    tmp_queue: EventQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Store an event "far in the past" by manipulating received_at_ms directly
    import sqlite3

    now = time.time()
    old_time_ms = int((now - 48 * 3600) * 1000)  # 48 hours ago

    db_path = tmp_queue.db_path
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO events (event_type, app_user_id, timestamp_ms, received_at_ms, payload) "
        "VALUES (?, ?, ?, ?, ?)",
        ("RENEWAL", "old_user", old_time_ms, old_time_ms, "{}"),
    )
    conn.commit()
    conn.close()

    # Recent event
    tmp_queue.store_event("BILLING_ISSUE", "new_user", {})

    # Default 24h — should only see new event
    events = tmp_queue.query_events(since_hours=24)
    assert len(events) == 1
    assert events[0].app_user_id == "new_user"

    # 72h — should see both
    events = tmp_queue.query_events(since_hours=72)
    assert len(events) == 2


def test_get_stats_empty(tmp_queue: EventQueue) -> None:
    stats = tmp_queue.get_stats()
    assert stats["total_events"] == 0
    assert stats["by_event_type"] == {}
    assert stats["oldest_event_age_hours"] is None
    assert stats["newest_event_age_seconds"] is None


def test_get_stats_with_events(tmp_queue: EventQueue) -> None:
    tmp_queue.store_event("RENEWAL", "u1", {})
    tmp_queue.store_event("RENEWAL", "u2", {})
    tmp_queue.store_event("BILLING_ISSUE", "u3", {})

    stats = tmp_queue.get_stats()
    assert stats["total_events"] == 3
    assert stats["by_event_type"]["RENEWAL"] == 2
    assert stats["by_event_type"]["BILLING_ISSUE"] == 1
    assert stats["oldest_event_age_hours"] is not None
    assert stats["newest_event_age_seconds"] is not None


def test_purge_old_events(tmp_queue: EventQueue) -> None:
    import sqlite3

    now = time.time()
    old_time_ms = int((now - 200 * 3600) * 1000)  # 200h ago

    db_path = tmp_queue.db_path
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO events (event_type, app_user_id, timestamp_ms, received_at_ms, payload) "
        "VALUES (?, ?, ?, ?, ?)",
        ("RENEWAL", "old_user", old_time_ms, old_time_ms, "{}"),
    )
    conn.commit()
    conn.close()

    tmp_queue.store_event("BILLING_ISSUE", "new_user", {})

    deleted = tmp_queue.purge_old_events(older_than_hours=168)
    assert deleted == 1

    remaining = tmp_queue.query_events(since_hours=9999)
    assert len(remaining) == 1
    assert remaining[0].app_user_id == "new_user"


def test_multiple_users_ordering(tmp_queue: EventQueue) -> None:
    """Events returned most-recent first."""
    tmp_queue.store_event("INITIAL_PURCHASE", "u1", {})
    time.sleep(0.01)
    tmp_queue.store_event("RENEWAL", "u1", {})

    events = tmp_queue.query_events(app_user_id="u1")
    assert events[0].event_type == "RENEWAL"
    assert events[1].event_type == "INITIAL_PURCHASE"


def test_queue_uses_env_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = str(tmp_path / "env_events.db")
    monkeypatch.setenv("RC_EVENT_DB_PATH", db)
    queue = EventQueue()
    assert queue.db_path == Path(db)


# ── MCP tool integration (server.call_tool) ───────────────────────────────────


@pytest.fixture()
def patched_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> EventQueue:
    """Patch EventQueue in server module to use a temp DB."""
    db_path = tmp_path / "mcp_test_events.db"
    queue = EventQueue(db_path=db_path)

    # Patch EventQueue() call in server module to return our tmp queue
    from rc_mcp_server import server

    monkeypatch.setattr(
        server,
        "EventQueue",
        lambda *a, **kw: queue,
    )
    return queue


@pytest.mark.asyncio()
async def test_mcp_rc_queue_status_empty(patched_queue: EventQueue) -> None:
    from rc_mcp_server.server import call_tool

    result = await call_tool("rc_queue_status", {})
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["total_events"] == 0


@pytest.mark.asyncio()
async def test_mcp_rc_queue_status_with_events(patched_queue: EventQueue) -> None:
    from rc_mcp_server.server import call_tool

    patched_queue.store_event("BILLING_ISSUE", "u1", {})
    patched_queue.store_event("RENEWAL", "u2", {})

    result = await call_tool("rc_queue_status", {})
    data = json.loads(result[0].text)
    assert data["total_events"] == 2
    assert "BILLING_ISSUE" in data["by_event_type"]


@pytest.mark.asyncio()
async def test_mcp_rc_get_recent_events_empty(patched_queue: EventQueue) -> None:
    from rc_mcp_server.server import call_tool

    result = await call_tool("rc_get_recent_events", {})
    data = json.loads(result[0].text)
    assert data["count"] == 0
    assert data["events"] == []


@pytest.mark.asyncio()
async def test_mcp_rc_get_recent_events_all(patched_queue: EventQueue) -> None:
    from rc_mcp_server.server import call_tool

    patched_queue.store_event("RENEWAL", "alice", {"type": "RENEWAL"})
    patched_queue.store_event("CANCELLATION", "bob", {"type": "CANCELLATION"})

    result = await call_tool("rc_get_recent_events", {})
    data = json.loads(result[0].text)
    assert data["count"] == 2


@pytest.mark.asyncio()
async def test_mcp_rc_get_recent_events_filtered(patched_queue: EventQueue) -> None:
    from rc_mcp_server.server import call_tool

    patched_queue.store_event("BILLING_ISSUE", "alice", {})
    patched_queue.store_event("RENEWAL", "alice", {})
    patched_queue.store_event("BILLING_ISSUE", "bob", {})

    result = await call_tool(
        "rc_get_recent_events",
        {"app_user_id": "alice", "event_type": "BILLING_ISSUE"},
    )
    data = json.loads(result[0].text)
    assert data["count"] == 1
    assert data["events"][0]["app_user_id"] == "alice"
    assert data["events"][0]["event_type"] == "BILLING_ISSUE"


@pytest.mark.asyncio()
async def test_mcp_rc_get_recent_events_limit_capped(patched_queue: EventQueue) -> None:
    from rc_mcp_server.server import call_tool

    # limit is capped at 100
    result = await call_tool("rc_get_recent_events", {"limit": 999})
    data = json.loads(result[0].text)
    # No error — just respects cap
    assert "count" in data


# ── Webhook server integration tests ─────────────────────────────────────────


@pytest.fixture()
def webhook_app(tmp_path: Path) -> object:
    """Build a test webhook app with a temp DB."""
    from rc_mcp_server.webhook_server import _build_app

    db_path = str(tmp_path / "webhook_test.db")
    return _build_app(db_path=db_path)


@pytest.fixture()
def webhook_client(webhook_app: object) -> object:
    try:
        from fastapi.testclient import TestClient

        return TestClient(webhook_app)
    except ImportError:
        pytest.skip("fastapi not installed — skipping webhook server tests")


def test_webhook_health(webhook_client: object) -> None:
    resp = webhook_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_webhook_stats_empty(webhook_client: object) -> None:
    resp = webhook_client.get("/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_events"] == 0


def test_webhook_receive_event(webhook_client: object) -> None:
    payload = {
        "event": {
            "type": "INITIAL_PURCHASE",
            "app_user_id": "user_test_001",
            "event_timestamp_ms": int(time.time() * 1000),
        }
    }
    resp = webhook_client.post("/webhooks/revenuecat", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert "id" in data


def test_webhook_stats_after_event(webhook_client: object) -> None:
    payload = {"event": {"type": "BILLING_ISSUE", "app_user_id": "user_xyz"}}
    webhook_client.post("/webhooks/revenuecat", json=payload)

    resp = webhook_client.get("/stats")
    data = resp.json()
    assert data["total_events"] == 1
    assert data["by_event_type"]["BILLING_ISSUE"] == 1


def test_webhook_bare_event_no_wrapper(webhook_client: object) -> None:
    """RC sometimes sends bare event objects (no 'event' wrapper)."""
    payload = {"type": "RENEWAL", "app_user_id": "user_bare"}
    resp = webhook_client.post("/webhooks/revenuecat", json=payload)
    assert resp.status_code == 200


def test_webhook_fallback_app_user_id(webhook_client: object) -> None:
    """original_app_user_id used as fallback when app_user_id absent."""
    payload = {
        "event": {
            "type": "TRANSFER",
            "original_app_user_id": "original_user",
        }
    }
    resp = webhook_client.post("/webhooks/revenuecat", json=payload)
    assert resp.status_code == 200


def test_webhook_invalid_json(webhook_client: object) -> None:
    # FastAPI returns 422 Unprocessable Entity for malformed JSON bodies
    resp = webhook_client.post(
        "/webhooks/revenuecat",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422


def test_webhook_auth_required() -> None:
    """When auth_key is set, requests without it are rejected."""
    try:
        import tempfile

        from fastapi.testclient import TestClient

        from rc_mcp_server.webhook_server import _build_app

        with tempfile.TemporaryDirectory() as tmp:
            app = _build_app(db_path=f"{tmp}/auth_test.db", auth_key="secret-key")
            client = TestClient(app, raise_server_exceptions=False)

            # No auth header
            resp = client.post("/webhooks/revenuecat", json={"event": {"type": "TEST"}})
            assert resp.status_code == 401

            # Wrong auth
            resp = client.post(
                "/webhooks/revenuecat",
                json={"event": {"type": "TEST"}},
                headers={"Authorization": "wrong"},
            )
            assert resp.status_code == 401

            # Correct auth
            resp = client.post(
                "/webhooks/revenuecat",
                json={"event": {"type": "TEST", "app_user_id": "u"}},
                headers={"Authorization": "secret-key"},
            )
            assert resp.status_code == 200
    except ImportError:
        pytest.skip("fastapi not installed")
