"""Standalone RevenueCat webhook receiver for rc-mcp-server.

Receives RC webhook events and writes them to the shared SQLite event queue,
which the MCP server can then query via rc_get_recent_events / rc_queue_status.

Usage:
    rc-mcp-webhook [--port 8765] [--db /path/to/events.db] [--auth-key sk_...]

Environment variables (override CLI flags):
    RC_EVENT_DB_PATH    — SQLite DB path (default: ~/.rc-mcp-events.db)
    RC_WEBHOOK_SECRET   — If set, verifies X-RevenueCat-Auth header on requests

RevenueCat webhook config:
    Set your webhook URL to: http://your-host:8765/webhooks/revenuecat
    Optional: set the auth header to match RC_WEBHOOK_SECRET

Endpoints:
    POST /webhooks/revenuecat   — receive RC events (main endpoint)
    GET  /health                — health check
    GET  /stats                 — queue statistics
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import Any

from .event_queue import EventQueue

logger = logging.getLogger(__name__)


def _build_app(db_path: str | None = None, auth_key: str | None = None) -> Any:
    """Build and return the FastAPI app. Import is deferred so the module can
    be imported even when fastapi/uvicorn are not installed."""
    try:
        from fastapi import FastAPI, Header, HTTPException, status
    except ImportError as exc:
        raise ImportError(
            "fastapi is required for the webhook server. "
            "Install it with: pip install 'rc-mcp-server[webhook]'"
        ) from exc

    queue = EventQueue(db_path)
    app = FastAPI(title="rc-mcp-webhook", version="0.4.0")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "timestamp": int(time.time())}

    @app.get("/stats")
    async def stats() -> dict[str, Any]:
        return queue.get_stats()

    @app.post("/webhooks/revenuecat", status_code=status.HTTP_200_OK)
    async def receive_webhook(
        body: dict[str, Any],
        authorization: str | None = Header(default=None),
    ) -> dict[str, str]:
        # Optional auth header check
        secret = auth_key or os.environ.get("RC_WEBHOOK_SECRET")
        if secret:
            provided = authorization or ""
            if provided != secret:
                logger.warning("Webhook auth failed: invalid Authorization header")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid Authorization header",
                )

        # RC wraps events in {"event": {...}}
        event_data = body.get("event", body)

        event_type = event_data.get("type", "UNKNOWN")
        # RC uses "app_user_id" in most events; fall back to "original_app_user_id"
        app_user_id = (
            event_data.get("app_user_id")
            or event_data.get("original_app_user_id")
            or "unknown"
        )
        # RC timestamps are in ms; store as-is
        event_time_ms = event_data.get("event_timestamp_ms")
        timestamp_ms = int(event_time_ms) if event_time_ms else None

        row_id = queue.store_event(
            event_type=event_type,
            app_user_id=app_user_id,
            payload=event_data,
            timestamp_ms=timestamp_ms,
        )
        logger.info(
            "Stored RC event %s for %s (id=%d)", event_type, app_user_id, row_id
        )
        return {"status": "accepted", "id": str(row_id)}

    return app


def main() -> None:
    """Entry point for rc-mcp-webhook CLI."""
    parser = argparse.ArgumentParser(
        description="RevenueCat webhook receiver — writes events to the rc-mcp-server event queue"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to listen on (default: 8765)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite DB path (default: RC_EVENT_DB_PATH env or ~/.rc-mcp-events.db)",
    )
    parser.add_argument(
        "--auth-key",
        default=None,
        help="Expected Authorization header value (overrides RC_WEBHOOK_SECRET env)",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        import uvicorn
    except ImportError:
        print(
            "uvicorn is required for the webhook server. "
            "Install it with: pip install 'rc-mcp-server[webhook]'",
            file=sys.stderr,
        )
        sys.exit(1)

    db_path = args.db or os.environ.get("RC_EVENT_DB_PATH")
    app = _build_app(db_path=db_path, auth_key=args.auth_key)

    logger.info("Starting rc-mcp-webhook on %s:%d", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    main()
