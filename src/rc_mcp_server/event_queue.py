"""SQLite-backed event queue for RevenueCat webhook events.

Usage:
    from rc_mcp_server.event_queue import EventQueue

    q = EventQueue("/var/lib/rc-mcp/events.db")
    q.store_event("BILLING_ISSUE", "user_123", {...})
    events = q.query_events(app_user_id="user_123", limit=20)

Environment:
    RC_EVENT_DB_PATH  — path to SQLite DB (default: ~/.rc-mcp-events.db)
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path.home() / ".rc-mcp-events.db"

# RC webhook event types (complete list as of v1)
KNOWN_EVENT_TYPES = frozenset(
    [
        "INITIAL_PURCHASE",
        "RENEWAL",
        "PRODUCT_CHANGE",
        "CANCELLATION",
        "UNCANCELLATION",
        "BILLING_ISSUE",
        "SUBSCRIBER_ALIAS",
        "SUBSCRIPTION_PAUSED",
        "EXPIRATION",
        "TRANSFER",
        "TEST",
    ]
)


@dataclass
class QueuedEvent:
    id: int
    event_type: str
    app_user_id: str
    timestamp_ms: int
    received_at_ms: int
    payload: dict[str, Any]

    @property
    def age_seconds(self) -> float:
        return (time.time() * 1000 - self.received_at_ms) / 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "app_user_id": self.app_user_id,
            "timestamp_ms": self.timestamp_ms,
            "received_at_ms": self.received_at_ms,
            "age_seconds": round(self.age_seconds, 1),
            "payload": self.payload,
        }


class EventQueue:
    """SQLite-backed queue for RevenueCat webhook events.

    Thread-safe for concurrent writes (webhook receiver) and reads (MCP tools)
    via WAL journal mode.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = os.environ.get("RC_EVENT_DB_PATH", str(DEFAULT_DB_PATH))
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type      TEXT NOT NULL,
                    app_user_id     TEXT NOT NULL,
                    timestamp_ms    INTEGER NOT NULL,
                    received_at_ms  INTEGER NOT NULL,
                    payload         TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_user ON events(app_user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_received "
                "ON events(received_at_ms DESC)"
            )

    def store_event(
        self,
        event_type: str,
        app_user_id: str,
        payload: dict[str, Any],
        timestamp_ms: int | None = None,
    ) -> int:
        """Store a webhook event. Returns the inserted row id."""
        if timestamp_ms is None:
            timestamp_ms = int(time.time() * 1000)
        received_at_ms = int(time.time() * 1000)

        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO events (event_type, app_user_id, timestamp_ms, "
                "received_at_ms, payload) VALUES (?, ?, ?, ?, ?)",
                (
                    event_type,
                    app_user_id,
                    timestamp_ms,
                    received_at_ms,
                    json.dumps(payload),
                ),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def query_events(
        self,
        app_user_id: str | None = None,
        event_type: str | None = None,
        since_hours: float = 24,
        limit: int = 20,
    ) -> list[QueuedEvent]:
        """Query recent events with optional filters.

        Args:
            app_user_id: Filter to a specific subscriber (None = all users)
            event_type: Filter to a specific event type (None = all types)
            since_hours: Only return events received in the last N hours
            limit: Maximum number of results (most recent first)
        """
        since_ms = int((time.time() - since_hours * 3600) * 1000)

        conditions = ["received_at_ms >= ?"]
        params: list[Any] = [since_ms]

        if app_user_id is not None:
            conditions.append("app_user_id = ?")
            params.append(app_user_id)

        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type.upper())

        where = " AND ".join(conditions)
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM events WHERE {where} "
                f"ORDER BY received_at_ms DESC LIMIT ?",
                params,
            ).fetchall()

        return [
            QueuedEvent(
                id=row["id"],
                event_type=row["event_type"],
                app_user_id=row["app_user_id"],
                timestamp_ms=row["timestamp_ms"],
                received_at_ms=row["received_at_ms"],
                payload=json.loads(row["payload"]),
            )
            for row in rows
        ]

    def get_stats(self) -> dict[str, Any]:
        """Return queue statistics: total events, by type, oldest/newest."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            by_type = {
                row[0]: row[1]
                for row in conn.execute(
                    "SELECT event_type, COUNT(*) FROM events GROUP BY event_type "
                    "ORDER BY COUNT(*) DESC"
                ).fetchall()
            }
            oldest_row = conn.execute(
                "SELECT received_at_ms FROM events ORDER BY received_at_ms ASC LIMIT 1"
            ).fetchone()
            newest_row = conn.execute(
                "SELECT received_at_ms FROM events ORDER BY received_at_ms DESC LIMIT 1"
            ).fetchone()

        oldest_ms = oldest_row[0] if oldest_row else None
        newest_ms = newest_row[0] if newest_row else None
        now_ms = int(time.time() * 1000)

        return {
            "total_events": total,
            "by_event_type": by_type,
            "db_path": str(self.db_path),
            "oldest_event_age_hours": (
                round((now_ms - oldest_ms) / 3_600_000, 1) if oldest_ms else None
            ),
            "newest_event_age_seconds": (
                round((now_ms - newest_ms) / 1000, 1) if newest_ms else None
            ),
        }

    def purge_old_events(self, older_than_hours: float = 168) -> int:
        """Delete events older than N hours (default: 7 days). Returns count deleted."""
        cutoff_ms = int((time.time() - older_than_hours * 3600) * 1000)
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM events WHERE received_at_ms < ?", (cutoff_ms,)
            )
            return cur.rowcount
