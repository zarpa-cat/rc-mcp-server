"""Tests for Phase 3: Resources, Prompts, and rc_get_subscription_status tool."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from rc_mcp_server.models import (
    ActiveSubscriptionSummary,
    Subscriber,
    SubscriptionStatus,
)
from rc_mcp_server.server import (
    call_tool,
    get_prompt,
    list_prompts,
    list_resource_templates,
    list_tools,
    read_resource,
)

# ── SubscriptionStatus model ──────────────────────────────────────────────────


def test_active_subscription_summary_billing_issue():
    s = ActiveSubscriptionSummary(
        product_identifier="premium_monthly",
        billing_issues_detected_at=datetime(2026, 3, 10, tzinfo=UTC),
    )
    assert s.has_billing_issue is True
    assert s.is_canceling is False
    assert s.is_in_grace_period is False


def test_active_subscription_summary_canceling():
    s = ActiveSubscriptionSummary(
        product_identifier="premium_monthly",
        unsubscribe_detected_at=datetime(2026, 3, 14, tzinfo=UTC),
    )
    assert s.is_canceling is True
    assert s.has_billing_issue is False


def test_active_subscription_summary_grace_period():
    future = datetime(2099, 1, 1, tzinfo=UTC)
    s = ActiveSubscriptionSummary(
        product_identifier="premium_monthly",
        grace_period_expires_date=future,
    )
    assert s.is_in_grace_period is True


def test_active_subscription_summary_grace_period_expired():
    past = datetime(2020, 1, 1, tzinfo=UTC)
    s = ActiveSubscriptionSummary(
        product_identifier="premium_monthly",
        grace_period_expires_date=past,
    )
    assert s.is_in_grace_period is False


def test_subscription_status_has_any_active_true():
    status = SubscriptionStatus(
        app_user_id="user_1",
        active_entitlements=["premium"],
        active_subscriptions=[],
        has_any_active=True,
        has_billing_issues=False,
        is_any_canceling=False,
        is_any_in_grace_period=False,
        total_subscriptions=1,
        total_entitlements=1,
    )
    assert status.has_any_active is True
    assert status.app_user_id == "user_1"


def test_subscription_status_no_active():
    status = SubscriptionStatus(
        app_user_id="lapsed_user",
        active_entitlements=[],
        active_subscriptions=[],
        has_any_active=False,
        has_billing_issues=False,
        is_any_canceling=False,
        is_any_in_grace_period=False,
        total_subscriptions=0,
        total_entitlements=0,
    )
    assert status.has_any_active is False


# ── rc_get_subscription_status tool ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_tools_includes_subscription_status():
    tools = await list_tools()
    names = {t.name for t in tools}
    assert "rc_get_subscription_status" in names


@pytest.mark.asyncio
async def test_subscription_status_tool(sample_subscriber_payload):
    sub = Subscriber.model_validate(sample_subscriber_payload)
    status = SubscriptionStatus(
        app_user_id="test_user_123",
        active_entitlements=["premium"],
        active_subscriptions=[
            ActiveSubscriptionSummary(product_identifier="premium_monthly")
        ],
        has_any_active=True,
        has_billing_issues=False,
        is_any_canceling=False,
        is_any_in_grace_period=False,
        first_seen=sub.subscriber.first_seen,
        total_subscriptions=1,
        total_entitlements=1,
    )

    with patch.dict("os.environ", {"REVENUECAT_API_KEY": "sk_test"}):
        with patch("rc_mcp_server.server.RCClient") as mock_rc:
            mock_instance = AsyncMock()
            mock_instance.get_subscription_status.return_value = status
            mock_rc.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_rc.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await call_tool(
                "rc_get_subscription_status", {"app_user_id": "test_user_123"}
            )

    assert len(result) == 1
    assert "test_user_123" in result[0].text
    assert "premium" in result[0].text
    assert "has_any_active" in result[0].text


@pytest.mark.asyncio
async def test_subscription_status_tool_no_api_key():
    with patch.dict("os.environ", {}, clear=True):
        import os

        os.environ.pop("REVENUECAT_API_KEY", None)
        result = await call_tool("rc_get_subscription_status", {"app_user_id": "user"})
    assert "REVENUECAT_API_KEY" in result[0].text


# ── Resource templates ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_resource_templates():
    templates = await list_resource_templates()
    uri_templates = {t.uriTemplate for t in templates}
    assert "rc://subscriber/{app_user_id}" in uri_templates
    assert "rc://offerings/{app_user_id}" in uri_templates


@pytest.mark.asyncio
async def test_list_resource_templates_have_descriptions():
    templates = await list_resource_templates()
    for t in templates:
        assert t.description is not None
        assert len(t.description) > 10


@pytest.mark.asyncio
async def test_list_resource_templates_json_mime():
    templates = await list_resource_templates()
    for t in templates:
        assert t.mimeType == "application/json"


# ── read_resource ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_subscriber_resource(sample_subscriber_payload):
    sub = Subscriber.model_validate(sample_subscriber_payload)

    with patch.dict("os.environ", {"REVENUECAT_API_KEY": "sk_test"}):
        with patch("rc_mcp_server.server.RCClient") as mock_rc:
            mock_instance = AsyncMock()
            mock_instance.get_subscriber.return_value = sub
            mock_rc.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_rc.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await read_resource("rc://subscriber/test_user_123")  # type: ignore[arg-type]

    import json

    data = json.loads(result)
    assert "subscriber" in data


@pytest.mark.asyncio
async def test_read_offerings_resource(sample_offerings_payload):
    from rc_mcp_server.models import Offering, OfferingsResponse

    offerings = OfferingsResponse(
        current_offering_id="default",
        offerings=[
            Offering(
                identifier="default",
                description="Default",
                packages=[],
            )
        ],
    )

    with patch.dict("os.environ", {"REVENUECAT_API_KEY": "sk_test"}):
        with patch("rc_mcp_server.server.RCClient") as mock_rc:
            mock_instance = AsyncMock()
            mock_instance.get_offerings.return_value = offerings
            mock_rc.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_rc.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await read_resource("rc://offerings/test_user_123")  # type: ignore[arg-type]

    import json

    data = json.loads(result)
    assert "current_offering_id" in data
    assert data["current_offering_id"] == "default"


@pytest.mark.asyncio
async def test_read_resource_no_api_key():
    with patch.dict("os.environ", {}, clear=True):
        import os

        os.environ.pop("REVENUECAT_API_KEY", None)
        with pytest.raises(ValueError, match="REVENUECAT_API_KEY"):
            await read_resource("rc://subscriber/user123")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_read_resource_unknown_scheme():
    with patch.dict("os.environ", {"REVENUECAT_API_KEY": "sk_test"}):
        with pytest.raises(ValueError, match="Unsupported resource URI"):
            await read_resource("rc://unknown/user123")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_read_resource_missing_user_id():
    with patch.dict("os.environ", {"REVENUECAT_API_KEY": "sk_test"}):
        with pytest.raises(ValueError, match="No app_user_id"):
            await read_resource("rc://subscriber/")  # type: ignore[arg-type]


# ── Prompts ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_prompts():
    prompts = await list_prompts()
    names = {p.name for p in prompts}
    assert "audit_subscriber" in names
    assert "retention_check" in names


@pytest.mark.asyncio
async def test_list_prompts_have_arguments():
    prompts = await list_prompts()
    for p in prompts:
        assert p.arguments is not None
        assert len(p.arguments) >= 1
        arg_names = {a.name for a in p.arguments}
        assert "app_user_id" in arg_names


@pytest.mark.asyncio
async def test_list_prompts_app_user_id_required():
    prompts = await list_prompts()
    for p in prompts:
        for arg in p.arguments or []:
            if arg.name == "app_user_id":
                assert arg.required is True


@pytest.mark.asyncio
async def test_get_prompt_audit_subscriber():
    result = await get_prompt("audit_subscriber", {"app_user_id": "user_abc"})
    assert result.messages is not None
    assert len(result.messages) == 1
    msg = result.messages[0]
    assert msg.role == "user"
    assert "user_abc" in msg.content.text
    assert "rc_get_subscription_status" in msg.content.text
    assert "risk" in msg.content.text.lower()


@pytest.mark.asyncio
async def test_get_prompt_retention_check():
    result = await get_prompt("retention_check", {"app_user_id": "user_xyz"})
    assert result.messages is not None
    assert len(result.messages) == 1
    msg = result.messages[0]
    assert "user_xyz" in msg.content.text
    assert "rc_grant_entitlement" in msg.content.text
    assert "CRITICAL" in msg.content.text


@pytest.mark.asyncio
async def test_get_prompt_unknown_raises():
    with pytest.raises(ValueError, match="Unknown prompt"):
        await get_prompt("not_a_real_prompt", {})


@pytest.mark.asyncio
async def test_get_prompt_no_args_uses_placeholder():
    result = await get_prompt("audit_subscriber", None)
    msg = result.messages[0]
    assert "<app_user_id>" in msg.content.text
