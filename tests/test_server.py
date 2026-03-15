"""Tests for MCP server tool dispatch."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from rc_mcp_server.models import (
    EntitlementCheckResult,
    EntitlementGrantResult,
    Offering,
    OfferingsResponse,
    Subscriber,
)
from rc_mcp_server.server import call_tool, list_tools

# ── list_tools ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_tools_returns_all():
    tools = await list_tools()
    names = {t.name for t in tools}
    assert "rc_get_subscriber" in names
    assert "rc_check_entitlement" in names
    assert "rc_grant_entitlement" in names
    assert "rc_revoke_entitlement" in names
    assert "rc_get_offerings" in names
    assert "rc_set_attributes" in names
    assert "rc_delete_subscriber" in names


@pytest.mark.asyncio
async def test_list_tools_have_input_schemas():
    tools = await list_tools()
    for tool in tools:
        assert tool.inputSchema is not None
        assert "properties" in tool.inputSchema


# ── call_tool — no API key ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_api_key_returns_error():
    with patch.dict("os.environ", {}, clear=True):
        import os

        os.environ.pop("REVENUECAT_API_KEY", None)
        result = await call_tool("rc_get_subscriber", {"app_user_id": "user"})

    assert len(result) == 1
    assert "REVENUECAT_API_KEY" in result[0].text


# ── call_tool — rc_get_subscriber ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_subscriber_tool(sample_subscriber_payload):
    sub = Subscriber.model_validate(sample_subscriber_payload)

    with patch.dict("os.environ", {"REVENUECAT_API_KEY": "sk_test"}):
        with patch("rc_mcp_server.server.RCClient") as mock_rc:
            mock_instance = AsyncMock()
            mock_instance.get_subscriber.return_value = sub
            mock_rc.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_rc.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await call_tool(
                "rc_get_subscriber", {"app_user_id": "test_user_123"}
            )

    assert len(result) == 1
    assert "test_user_123" in result[0].text


# ── call_tool — rc_check_entitlement ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_entitlement_tool():
    check_result = EntitlementCheckResult(
        app_user_id="user_123",
        entitlement_identifier="premium",
        is_active=True,
    )

    with patch.dict("os.environ", {"REVENUECAT_API_KEY": "sk_test"}):
        with patch("rc_mcp_server.server.RCClient") as mock_rc:
            mock_instance = AsyncMock()
            mock_instance.check_entitlement.return_value = check_result
            mock_rc.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_rc.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await call_tool(
                "rc_check_entitlement",
                {"app_user_id": "user_123", "entitlement_identifier": "premium"},
            )

    assert "is_active" in result[0].text
    assert "true" in result[0].text.lower()


# ── call_tool — rc_grant_entitlement ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_entitlement_tool():
    grant_result = EntitlementGrantResult(
        app_user_id="user_123",
        entitlement_identifier="premium",
        success=True,
        message="Granted 'premium' (monthly) to user_123",
    )

    with patch.dict("os.environ", {"REVENUECAT_API_KEY": "sk_test"}):
        with patch("rc_mcp_server.server.RCClient") as mock_rc:
            mock_instance = AsyncMock()
            mock_instance.grant_promotional_entitlement.return_value = grant_result
            mock_rc.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_rc.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await call_tool(
                "rc_grant_entitlement",
                {
                    "app_user_id": "user_123",
                    "entitlement_identifier": "premium",
                    "duration": "monthly",
                },
            )

    assert "success" in result[0].text


# ── call_tool — rc_revoke_entitlement ────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoke_entitlement_tool():
    revoke_result = EntitlementGrantResult(
        app_user_id="user_123",
        entitlement_identifier="premium",
        success=True,
        message="Revoked 'premium' from user_123",
    )

    with patch.dict("os.environ", {"REVENUECAT_API_KEY": "sk_test"}):
        with patch("rc_mcp_server.server.RCClient") as mock_rc:
            mock_instance = AsyncMock()
            mock_instance.revoke_promotional_entitlements.return_value = revoke_result
            mock_rc.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_rc.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await call_tool(
                "rc_revoke_entitlement",
                {"app_user_id": "user_123", "entitlement_identifier": "premium"},
            )

    assert "success" in result[0].text


# ── call_tool — rc_get_offerings ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_offerings_tool():
    offerings_result = OfferingsResponse(
        current_offering_id="default",
        offerings=[
            Offering(identifier="default", description="Default offering", packages=[])
        ],
    )

    with patch.dict("os.environ", {"REVENUECAT_API_KEY": "sk_test"}):
        with patch("rc_mcp_server.server.RCClient") as mock_rc:
            mock_instance = AsyncMock()
            mock_instance.get_offerings.return_value = offerings_result
            mock_rc.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_rc.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await call_tool("rc_get_offerings", {"app_user_id": "user_123"})

    assert "default" in result[0].text


# ── call_tool — rc_set_attributes ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_attributes_tool():
    with patch.dict("os.environ", {"REVENUECAT_API_KEY": "sk_test"}):
        with patch("rc_mcp_server.server.RCClient") as mock_rc:
            mock_instance = AsyncMock()
            mock_instance.set_attributes.return_value = {
                "success": True,
                "app_user_id": "user_123",
                "attributes": {"cohort": "beta"},
            }
            mock_rc.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_rc.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await call_tool(
                "rc_set_attributes",
                {"app_user_id": "user_123", "attributes": {"cohort": "beta"}},
            )

    assert "success" in result[0].text


# ── call_tool — rc_delete_subscriber ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_subscriber_requires_confirm():
    with patch.dict("os.environ", {"REVENUECAT_API_KEY": "sk_test"}):
        with patch("rc_mcp_server.server.RCClient"):
            result = await call_tool(
                "rc_delete_subscriber",
                {"app_user_id": "user_123", "confirm": False},
            )

    assert "ERROR" in result[0].text
    assert "confirm=true" in result[0].text


@pytest.mark.asyncio
async def test_delete_subscriber_with_confirm():
    with patch.dict("os.environ", {"REVENUECAT_API_KEY": "sk_test"}):
        with patch("rc_mcp_server.server.RCClient") as mock_rc:
            mock_instance = AsyncMock()
            mock_instance.delete_subscriber.return_value = {"app_user_id": "user_123"}
            mock_rc.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_rc.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await call_tool(
                "rc_delete_subscriber",
                {"app_user_id": "user_123", "confirm": True},
            )

    assert "user_123" in result[0].text


# ── call_tool — unknown tool ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_tool_returns_error():
    with patch.dict("os.environ", {"REVENUECAT_API_KEY": "sk_test"}):
        with patch("rc_mcp_server.server.RCClient") as mock_rc:
            mock_instance = AsyncMock()
            mock_rc.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_rc.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await call_tool("rc_nonexistent_tool", {})

    assert "ERROR" in result[0].text
    assert "Unknown tool" in result[0].text


# ── call_tool — RCError propagation ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_rc_error_propagates_cleanly():
    from rc_mcp_server.client import RCError

    with patch.dict("os.environ", {"REVENUECAT_API_KEY": "sk_test"}):
        with patch("rc_mcp_server.server.RCClient") as mock_rc:
            mock_instance = AsyncMock()
            mock_instance.get_subscriber.side_effect = RCError(404, "Not found")
            mock_rc.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_rc.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await call_tool("rc_get_subscriber", {"app_user_id": "ghost"})

    assert "ERROR" in result[0].text
    assert "404" in result[0].text
