"""RevenueCat MCP Server.

Exposes RevenueCat REST API as MCP tools, resources, and prompts for AI agents.
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

Resources (v0.3.0+):
    rc://subscriber/{app_user_id}   — full subscriber data
    rc://offerings/{app_user_id}    — available offerings for a subscriber

Prompts (v0.3.0+):
    audit_subscriber   — structured billing health analysis
    retention_check    — churn risk assessment
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any
from urllib.parse import urlparse

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .client import RCClient, RCError
from .event_queue import EventQueue

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
        types.Tool(
            name="rc_get_attributes",
            description=(
                "Fetch subscriber attributes (custom key/value metadata) as a clean dict. "
                "Use this to read current attribute values before updating them."
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
            name="rc_create_alias",
            description=(
                "Create an alias linking a new app user ID to an existing subscriber. "
                "Use for account linking: e.g. link an anonymous ID to an identified user "
                "after sign-in so their purchase history merges."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "app_user_id": {
                        "type": "string",
                        "description": "The existing RevenueCat app user ID",
                    },
                    "new_app_user_id": {
                        "type": "string",
                        "description": "The new user ID to link as an alias",
                    },
                },
                "required": ["app_user_id", "new_app_user_id"],
            },
        ),
        types.Tool(
            name="rc_batch_check_entitlements",
            description=(
                "Check an entitlement for multiple subscribers in parallel. "
                "Returns an aggregate summary (total/active/inactive) plus per-user results. "
                "Useful for cohort analysis, bulk gating decisions, or churn monitoring."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "app_user_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of RevenueCat app user IDs to check",
                    },
                    "entitlement_identifier": {
                        "type": "string",
                        "description": "The entitlement to check for all users",
                    },
                },
                "required": ["app_user_ids", "entitlement_identifier"],
            },
        ),
        types.Tool(
            name="rc_get_subscription_status",
            description=(
                "Get an agent-friendly billing summary for a subscriber. "
                "Returns: active entitlements (list), active subscriptions with product IDs, "
                "billing issue flags, cancellation status, grace period status, and management URL. "
                "Use this instead of rc_get_subscriber when you need a clean decision-ready view — "
                "e.g. 'is this user in trouble?' or 'what are their active plans?'."
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
            name="rc_get_recent_events",
            description=(
                "Query the local RevenueCat webhook event queue for recent billing events. "
                "Requires rc-mcp-webhook to be running and receiving events from RevenueCat. "
                "Returns events in reverse chronological order. Filter by subscriber, "
                "event type, or time window. "
                "Event types: INITIAL_PURCHASE, RENEWAL, CANCELLATION, BILLING_ISSUE, "
                "EXPIRATION, PRODUCT_CHANGE, UNCANCELLATION, SUBSCRIPTION_PAUSED, TRANSFER, TEST."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "app_user_id": {
                        "type": "string",
                        "description": "Filter to a specific subscriber (omit for all users)",
                    },
                    "event_type": {
                        "type": "string",
                        "description": (
                            "Filter to a specific event type, e.g. 'BILLING_ISSUE' or 'CANCELLATION' "
                            "(omit for all types)"
                        ),
                    },
                    "since_hours": {
                        "type": "number",
                        "description": "Only return events received in the last N hours (default: 24)",
                        "default": 24,
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum events to return (default: 20, max: 100)",
                        "default": 20,
                    },
                },
                "required": [],
            },
        ),
        types.Tool(
            name="rc_queue_status",
            description=(
                "Show statistics for the local RevenueCat webhook event queue. "
                "Returns: total stored events, count by event type, DB path, and age of "
                "oldest/newest events. Use to confirm the webhook receiver is working and "
                "events are flowing."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
    ]


@_app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    # ── Event queue tools (no RC API call needed) ────────────────────────────
    if name == "rc_get_recent_events":
        try:
            queue = EventQueue()
            limit = min(int(arguments.get("limit", 20)), 100)
            since_hours = float(arguments.get("since_hours", 24))
            events = queue.query_events(
                app_user_id=arguments.get("app_user_id"),
                event_type=arguments.get("event_type"),
                since_hours=since_hours,
                limit=limit,
            )
            return _ok(
                {
                    "count": len(events),
                    "since_hours": since_hours,
                    "events": [e.to_dict() for e in events],
                }
            )
        except Exception as e:
            return _err(f"Event queue error: {e}")

    if name == "rc_queue_status":
        try:
            queue = EventQueue()
            return _ok(queue.get_stats())
        except Exception as e:
            return _err(f"Event queue error: {e}")

    # ── RC API tools ──────────────────────────────────────────────────────────
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

            elif name == "rc_get_attributes":
                result = await rc.get_attributes(arguments["app_user_id"])
                return _ok(
                    {"app_user_id": arguments["app_user_id"], "attributes": result}
                )

            elif name == "rc_create_alias":
                result = await rc.create_alias(
                    arguments["app_user_id"],
                    arguments["new_app_user_id"],
                )
                return _ok(result.model_dump(mode="json"))

            elif name == "rc_batch_check_entitlements":
                result = await rc.batch_check_entitlements(
                    arguments["app_user_ids"],
                    arguments["entitlement_identifier"],
                )
                return _ok(result.model_dump(mode="json"))

            elif name == "rc_get_subscription_status":
                result = await rc.get_subscription_status(arguments["app_user_id"])
                return _ok(result.model_dump(mode="json"))

            else:
                return _err(f"Unknown tool: {name}")

    except RCError as e:
        return _err(str(e))
    except Exception as e:
        logger.exception("Unexpected error in tool %s", name)
        return _err(f"Unexpected error: {e}")

    except RCError as e:
        return _err(str(e))
    except Exception as e:
        logger.exception("Unexpected error in tool %s", name)
        return _err(f"Unexpected error: {e}")


# ── Resources ────────────────────────────────────────────────────────────────
# URI scheme: rc://subscriber/{app_user_id}  and  rc://offerings/{app_user_id}


@_app.list_resource_templates()
async def list_resource_templates() -> list[types.ResourceTemplate]:
    return [
        types.ResourceTemplate(
            name="rc-subscriber",
            uriTemplate="rc://subscriber/{app_user_id}",
            description=(
                "Full RevenueCat subscriber record for a given app_user_id. "
                "Includes entitlements, subscriptions, and custom attributes."
            ),
            mimeType="application/json",
        ),
        types.ResourceTemplate(
            name="rc-offerings",
            uriTemplate="rc://offerings/{app_user_id}",
            description=(
                "Available RevenueCat offerings for a given app_user_id, "
                "including packages, products, and the current offering ID."
            ),
            mimeType="application/json",
        ),
    ]


@_app.list_resources()
async def list_resources() -> list[types.Resource]:
    # Dynamic resources require knowing app_user_ids in advance — not applicable here.
    # Clients should use resource templates and supply their own app_user_ids.
    return []


@_app.read_resource()
async def read_resource(uri: types.AnyUrl) -> str:
    """Resolve a resource URI and return its content as a JSON string.

    Supported URI schemes:
        rc://subscriber/{app_user_id}
        rc://offerings/{app_user_id}
    """
    uri_str = str(uri)
    parsed = urlparse(uri_str)

    api_key = os.environ.get("REVENUECAT_API_KEY", "")
    if not api_key:
        raise ValueError(
            "REVENUECAT_API_KEY environment variable not set. "
            "Export it before running rc-mcp-server."
        )

    # URI path starts with "/" so strip it: /app_user_id → app_user_id
    app_user_id = parsed.path.lstrip("/")
    if not app_user_id:
        raise ValueError(f"No app_user_id in URI: {uri_str}")

    try:
        async with RCClient(api_key=api_key) as rc:
            if parsed.scheme == "rc" and parsed.netloc == "subscriber":
                result = await rc.get_subscriber(app_user_id)
                return json.dumps(result.model_dump(mode="json"), indent=2, default=str)

            elif parsed.scheme == "rc" and parsed.netloc == "offerings":
                result = await rc.get_offerings(app_user_id)
                return json.dumps(result.model_dump(mode="json"), indent=2, default=str)

            else:
                raise ValueError(
                    f"Unsupported resource URI: {uri_str}. "
                    "Expected rc://subscriber/... or rc://offerings/..."
                )
    except RCError as e:
        raise ValueError(str(e)) from e


# ── Prompts ───────────────────────────────────────────────────────────────────


@_app.list_prompts()
async def list_prompts() -> list[types.Prompt]:
    return [
        types.Prompt(
            name="audit_subscriber",
            description=(
                "Generate a structured billing health audit for a RevenueCat subscriber. "
                "Checks entitlement status, billing issues, grace period, cancellation signals, "
                "and outputs a plain-language summary with recommended actions."
            ),
            arguments=[
                types.PromptArgument(
                    name="app_user_id",
                    description="The RevenueCat app user ID to audit",
                    required=True,
                )
            ],
        ),
        types.Prompt(
            name="retention_check",
            description=(
                "Assess churn risk for a RevenueCat subscriber and recommend retention actions. "
                "Identifies cancellation intent, billing failures, and expiry windows, then "
                "suggests targeted interventions (comps, grace extensions, win-back offers)."
            ),
            arguments=[
                types.PromptArgument(
                    name="app_user_id",
                    description="The RevenueCat app user ID to assess",
                    required=True,
                )
            ],
        ),
    ]


@_app.get_prompt()
async def get_prompt(
    name: str, arguments: dict[str, str] | None
) -> types.GetPromptResult:
    args = arguments or {}
    app_user_id = args.get("app_user_id", "<app_user_id>")

    if name == "audit_subscriber":
        return types.GetPromptResult(
            description=f"Billing health audit for subscriber: {app_user_id}",
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(
                        type="text",
                        text=(
                            f"Please audit the billing health of RevenueCat subscriber `{app_user_id}`.\n\n"
                            "Steps:\n"
                            f"1. Call `rc_get_subscription_status` with app_user_id=`{app_user_id}`\n"
                            "2. Check for billing issues (`has_billing_issues`), grace period "
                            "(`is_any_in_grace_period`), and cancellation intent (`is_any_canceling`).\n"
                            "3. Summarise the subscriber's billing health in plain language:\n"
                            "   - What entitlements are active?\n"
                            "   - Are there any billing problems?\n"
                            "   - Is the subscriber at risk of churning?\n"
                            "   - What, if anything, should be done?\n"
                            "4. End with a risk level: LOW / MEDIUM / HIGH, with one-line rationale."
                        ),
                    ),
                )
            ],
        )

    elif name == "retention_check":
        return types.GetPromptResult(
            description=f"Churn risk assessment for subscriber: {app_user_id}",
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(
                        type="text",
                        text=(
                            f"Assess churn risk for RevenueCat subscriber `{app_user_id}` "
                            "and recommend retention actions.\n\n"
                            "Steps:\n"
                            f"1. Call `rc_get_subscription_status` with app_user_id=`{app_user_id}`\n"
                            "2. Check: billing issues, grace period status, cancellation intent, "
                            "expiry dates on active subscriptions.\n"
                            "3. Classify the churn risk:\n"
                            "   - CRITICAL: billing failure + grace period expiring soon\n"
                            "   - HIGH: unsubscribe detected or billing issues\n"
                            "   - MEDIUM: subscription expiring within 7 days\n"
                            "   - LOW: active, no signals\n"
                            "4. Recommend one concrete retention action:\n"
                            "   - CRITICAL/HIGH: use `rc_grant_entitlement` to extend access "
                            "(e.g. monthly comp)\n"
                            "   - MEDIUM: surface a win-back offer at next session\n"
                            "   - LOW: no action needed\n"
                            "5. If a grant is appropriate, output the exact `rc_grant_entitlement` "
                            "call parameters needed."
                        ),
                    ),
                )
            ],
        )

    else:
        raise ValueError(f"Unknown prompt: {name}")


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
