"""RevenueCat MCP Server.

Exposes RevenueCat REST API as MCP tools for AI agents.
Run via: rc-mcp-server (stdio transport)

Required env vars:
    REVENUECAT_API_KEY  — your RevenueCat secret key (sk_...)

Usage in Claude Desktop config:
    {
        "mcpServers": {
            "revenuecat": {
                "command": "rc-mcp-server",
                "env": { "REVENUECAT_API_KEY": "sk_..." }
            }
        }
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .client import RCClient, RCError

logger = logging.getLogger(__name__)

_app = Server("rc-mcp-server")


def _ok(data: Any) -> list[types.TextContent]:
    text = json.dumps(data, indent=2, default=str)
    return [types.TextContent(type="text", text=text)]


def _err(msg: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=f"ERROR: {msg}")]


@_app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="rc_get_subscriber",
            description=(
                "Fetch full subscriber info from RevenueCat including entitlements, "
                "subscriptions, and metadata. Use this to check a user's current "
                "subscription status."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "app_user_id": {
                        "type": "string",
                        "description": "The RevenueCat app user ID (e.g. '$RCAnonymousID:...' or your own user ID)",
                    }
                },
                "required": ["app_user_id"],
            },
        ),
        types.Tool(
            name="rc_check_entitlement",
            description=(
                "Check if a subscriber currently has a specific entitlement active. "
                "Returns is_active (bool), expiry date, and grace period info. "
                "Use this for gating features behind paywalls."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "app_user_id": {
                        "type": "string",
                        "description": "The RevenueCat app user ID",
                    },
                    "entitlement_identifier": {
                        "type": "string",
                        "description": "The entitlement identifier (e.g. 'premium', 'pro')",
                    },
                },
                "required": ["app_user_id", "entitlement_identifier"],
            },
        ),
        types.Tool(
            name="rc_grant_entitlement",
            description=(
                "Grant a promotional entitlement to a subscriber. Use this to give "
                "free access, trial extensions, or comp access. Duration options: "
                "daily, weekly, monthly, two_month, three_month, six_month, yearly, lifetime."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "app_user_id": {
                        "type": "string",
                        "description": "The RevenueCat app user ID",
                    },
                    "entitlement_identifier": {
                        "type": "string",
                        "description": "The entitlement identifier to grant",
                    },
                    "duration": {
                        "type": "string",
                        "description": "Duration: daily|weekly|monthly|two_month|three_month|six_month|yearly|lifetime",
                        "default": "monthly",
                    },
                },
                "required": ["app_user_id", "entitlement_identifier"],
            },
        ),
        types.Tool(
            name="rc_revoke_entitlement",
            description=(
                "Revoke all promotional entitlements with a given identifier from a subscriber. "
                "Only affects promotional grants — does not cancel paid subscriptions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "app_user_id": {
                        "type": "string",
                        "description": "The RevenueCat app user ID",
                    },
                    "entitlement_identifier": {
                        "type": "string",
                        "description": "The entitlement identifier to revoke",
                    },
                },
                "required": ["app_user_id", "entitlement_identifier"],
            },
        ),
        types.Tool(
            name="rc_get_offerings",
            description=(
                "Fetch available offerings for a subscriber, including packages and products. "
                "Use this to see what plans are available and which is the current offering."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "app_user_id": {
                        "type": "string",
                        "description": "The RevenueCat app user ID",
                    }
                },
                "required": ["app_user_id"],
            },
        ),
        types.Tool(
            name="rc_set_attributes",
            description=(
                "Set subscriber attributes (custom key/value metadata). Use this to tag "
                "subscribers with cohort, plan, source, or any custom dimension. "
                "Set value to null to delete an attribute."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "app_user_id": {
                        "type": "string",
                        "description": "The RevenueCat app user ID",
                    },
                    "attributes": {
                        "type": "object",
                        "description": "Key/value pairs. Value can be string or null (to delete).",
                        "additionalProperties": {"type": ["string", "null"]},
                    },
                },
                "required": ["app_user_id", "attributes"],
            },
        ),
        types.Tool(
            name="rc_delete_subscriber",
            description=(
                "Delete a subscriber and all their purchase history from RevenueCat. "
                "IRREVERSIBLE. Use with caution — primarily for GDPR/CCPA deletion requests."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "app_user_id": {
                        "type": "string",
                        "description": "The RevenueCat app user ID to delete",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to confirm deletion",
                    },
                },
                "required": ["app_user_id", "confirm"],
            },
        ),
    ]


@_app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    api_key = os.environ.get("REVENUECAT_API_KEY", "")
    if not api_key:
        return _err(
            "REVENUECAT_API_KEY environment variable not set. "
            "Export it before running rc-mcp-server."
        )

    try:
        async with RCClient(api_key=api_key) as rc:
            if name == "rc_get_subscriber":
                result = await rc.get_subscriber(arguments["app_user_id"])
                return _ok(result.model_dump(mode="json"))

            elif name == "rc_check_entitlement":
                result = await rc.check_entitlement(
                    arguments["app_user_id"],
                    arguments["entitlement_identifier"],
                )
                return _ok(result.model_dump(mode="json"))

            elif name == "rc_grant_entitlement":
                result = await rc.grant_promotional_entitlement(
                    arguments["app_user_id"],
                    arguments["entitlement_identifier"],
                    duration=arguments.get("duration", "monthly"),
                )
                return _ok(result.model_dump(mode="json"))

            elif name == "rc_revoke_entitlement":
                result = await rc.revoke_promotional_entitlements(
                    arguments["app_user_id"],
                    arguments["entitlement_identifier"],
                )
                return _ok(result.model_dump(mode="json"))

            elif name == "rc_get_offerings":
                result = await rc.get_offerings(arguments["app_user_id"])
                return _ok(result.model_dump(mode="json"))

            elif name == "rc_set_attributes":
                result = await rc.set_attributes(
                    arguments["app_user_id"],
                    arguments["attributes"],
                )
                return _ok(result)

            elif name == "rc_delete_subscriber":
                if not arguments.get("confirm"):
                    return _err(
                        "Deletion requires confirm=true. "
                        "This operation is irreversible."
                    )
                result = await rc.delete_subscriber(arguments["app_user_id"])
                return _ok(result)

            else:
                return _err(f"Unknown tool: {name}")

    except RCError as e:
        return _err(str(e))
    except Exception as e:
        logger.exception("Unexpected error in tool %s", name)
        return _err(f"Unexpected error: {e}")


def main() -> None:
    """Entry point for rc-mcp-server CLI."""
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_run())


async def _run() -> None:
    async with stdio_server() as streams:
        await _app.run(
            streams[0],
            streams[1],
            _app.create_initialization_options(),
        )


if __name__ == "__main__":
    main()
