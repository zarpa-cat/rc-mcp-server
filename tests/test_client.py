"""Tests for RCClient using pytest-httpx."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from rc_mcp_server.client import RCClient, RCError


@pytest.fixture
def api_key() -> str:
    return "sk_test_abc123"


@pytest.fixture
def client(api_key: str) -> RCClient:
    return RCClient(api_key=api_key)


def make_response(status: int, body: dict) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        content=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        request=httpx.Request("GET", "https://api.revenuecat.com/test"),
    )


# ── Constructor ───────────────────────────────────────────────────────────────


def test_client_requires_api_key():
    with patch.dict("os.environ", {}, clear=True):
        import os

        os.environ.pop("REVENUECAT_API_KEY", None)
        with pytest.raises(ValueError, match="API key required"):
            RCClient(api_key="")


def test_client_reads_api_key_from_env():
    with patch.dict("os.environ", {"REVENUECAT_API_KEY": "sk_from_env"}):
        c = RCClient()
        assert c.api_key == "sk_from_env"


# ── get_subscriber ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_subscriber_success(client, sample_subscriber_payload):
    mock_response = make_response(200, sample_subscriber_payload)

    with patch.object(client._client, "get", new=AsyncMock(return_value=mock_response)):
        sub = await client.get_subscriber("test_user_123")

    assert sub.subscriber.original_app_user_id == "test_user_123"
    assert "premium" in sub.subscriber.entitlements


@pytest.mark.asyncio
async def test_get_subscriber_not_found(client):
    mock_response = make_response(404, {"message": "Subscriber not found"})

    with patch.object(client._client, "get", new=AsyncMock(return_value=mock_response)):
        with pytest.raises(RCError) as exc_info:
            await client.get_subscriber("unknown_user")

    assert exc_info.value.status == 404


@pytest.mark.asyncio
async def test_get_subscriber_unauthorized(client):
    mock_response = make_response(401, {"message": "Invalid API key"})

    with patch.object(client._client, "get", new=AsyncMock(return_value=mock_response)):
        with pytest.raises(RCError) as exc_info:
            await client.get_subscriber("user")

    assert exc_info.value.status == 401


# ── check_entitlement ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_entitlement_active(client, sample_subscriber_payload):
    mock_response = make_response(200, sample_subscriber_payload)

    with patch.object(client._client, "get", new=AsyncMock(return_value=mock_response)):
        result = await client.check_entitlement("test_user_123", "premium")

    assert result.is_active is True
    assert result.entitlement_identifier == "premium"
    assert result.product_identifier == "monthly_premium"


@pytest.mark.asyncio
async def test_check_entitlement_not_present(client, sample_subscriber_payload):
    mock_response = make_response(200, sample_subscriber_payload)

    with patch.object(client._client, "get", new=AsyncMock(return_value=mock_response)):
        result = await client.check_entitlement("test_user_123", "enterprise")

    assert result.is_active is False
    assert result.expires_date is None


# ── grant_promotional_entitlement ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grant_entitlement_success(client):
    mock_response = make_response(200, {})

    with patch.object(
        client._client, "post", new=AsyncMock(return_value=mock_response)
    ):
        result = await client.grant_promotional_entitlement(
            "user_123", "premium", duration="monthly"
        )

    assert result.success is True
    assert result.entitlement_identifier == "premium"
    assert "monthly" in result.message


@pytest.mark.asyncio
async def test_grant_entitlement_default_duration(client):
    mock_response = make_response(200, {})
    captured_payload = {}

    async def mock_post(url, **kwargs):
        captured_payload.update(kwargs.get("json", {}))
        return mock_response

    with patch.object(client._client, "post", new=mock_post):
        await client.grant_promotional_entitlement("user_123", "premium")

    assert captured_payload["duration"] == "lifetime"


@pytest.mark.asyncio
async def test_grant_entitlement_api_error(client):
    mock_response = make_response(422, {"message": "Invalid duration"})

    with patch.object(
        client._client, "post", new=AsyncMock(return_value=mock_response)
    ):
        with pytest.raises(RCError) as exc_info:
            await client.grant_promotional_entitlement(
                "user_123", "premium", duration="invalid"
            )

    assert exc_info.value.status == 422


# ── revoke_promotional_entitlements ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoke_entitlement_success(client):
    mock_response = make_response(200, {})

    with patch.object(
        client._client, "delete", new=AsyncMock(return_value=mock_response)
    ):
        result = await client.revoke_promotional_entitlements("user_123", "premium")

    assert result.success is True


# ── get_offerings ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_offerings_success(client, sample_offerings_payload):
    mock_response = make_response(200, sample_offerings_payload)

    with patch.object(client._client, "get", new=AsyncMock(return_value=mock_response)):
        result = await client.get_offerings("user_123")

    assert result.current_offering_id == "default"
    assert len(result.offerings) == 1
    assert result.offerings[0].identifier == "default"


# ── set_attributes ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_attributes_success(client):
    mock_response = make_response(200, {})
    captured_payload = {}

    async def mock_post(url, **kwargs):
        captured_payload.update(kwargs.get("json", {}))
        return mock_response

    with patch.object(client._client, "post", new=mock_post):
        result = await client.set_attributes(
            "user_123", {"cohort": "beta", "source": "web"}
        )

    assert result["success"] is True
    attrs = captured_payload["attributes"]
    assert attrs["cohort"]["value"] == "beta"
    assert attrs["source"]["value"] == "web"


@pytest.mark.asyncio
async def test_set_attributes_delete(client):
    mock_response = make_response(200, {})
    captured_payload = {}

    async def mock_post(url, **kwargs):
        captured_payload.update(kwargs.get("json", {}))
        return mock_response

    with patch.object(client._client, "post", new=mock_post):
        await client.set_attributes("user_123", {"old_attr": None})

    assert captured_payload["attributes"]["old_attr"]["value"] is None


# ── delete_subscriber ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_subscriber_success(client):
    mock_response = make_response(200, {"app_user_id": "user_123"})

    with patch.object(
        client._client, "delete", new=AsyncMock(return_value=mock_response)
    ):
        result = await client.delete_subscriber("user_123")

    assert result["app_user_id"] == "user_123"


# ── context manager ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_context_manager(api_key):
    async with RCClient(api_key=api_key) as rc:
        assert rc.api_key == api_key


# ── get_attributes ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_attributes_returns_clean_dict(client, sample_subscriber_payload):
    mock_response = make_response(200, sample_subscriber_payload)

    with patch.object(client._client, "get", new=AsyncMock(return_value=mock_response)):
        result = await client.get_attributes("test_user_123")

    assert result["cohort"] == "beta"
    assert result["source"] == "web"


@pytest.mark.asyncio
async def test_get_attributes_empty(client):
    payload = {
        "request_date": "2026-03-15T06:00:00Z",
        "request_date_ms": 1741924800000,
        "subscriber": {
            "entitlements": {},
            "non_subscriptions": {},
            "original_app_user_id": "user_no_attrs",
            "other_purchases": {},
            "subscriptions": {},
            "subscriber_attributes": {},
        },
    }
    mock_response = make_response(200, payload)

    with patch.object(client._client, "get", new=AsyncMock(return_value=mock_response)):
        result = await client.get_attributes("user_no_attrs")

    assert result == {}


# ── create_alias ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_alias_success(client):
    mock_response = make_response(200, {})
    captured = {}

    async def mock_post(url, **kwargs):
        captured["url"] = url
        captured["body"] = kwargs.get("json", {})
        return mock_response

    with patch.object(client._client, "post", new=mock_post):
        result = await client.create_alias("anon_user_123", "identified_user_456")

    assert result.success is True
    assert result.alias == "identified_user_456"
    assert result.app_user_id == "anon_user_123"
    assert captured["body"]["new_app_user_id"] == "identified_user_456"
    assert "/aliases" in captured["url"]


@pytest.mark.asyncio
async def test_create_alias_error(client):
    mock_response = make_response(409, {"message": "Alias already exists"})

    with patch.object(
        client._client, "post", new=AsyncMock(return_value=mock_response)
    ):
        with pytest.raises(RCError) as exc:
            await client.create_alias("user_a", "user_b")
    assert exc.value.status == 409


# ── batch_check_entitlements ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_check_entitlements_mixed(client, sample_subscriber_payload):
    expired_payload = {
        "request_date": "2026-03-15T06:00:00Z",
        "request_date_ms": 1741924800000,
        "subscriber": {
            "entitlements": {
                "premium": {
                    "expires_date": "2025-01-01T00:00:00Z",
                    "product_identifier": "monthly_premium",
                    "purchase_date": "2024-12-01T00:00:00Z",
                }
            },
            "non_subscriptions": {},
            "original_app_user_id": "expired_user",
            "other_purchases": {},
            "subscriptions": {},
            "subscriber_attributes": {},
        },
    }

    call_count = {"n": 0}

    async def mock_get(url, **kwargs):
        call_count["n"] += 1
        if "active_user" in url:
            return make_response(200, sample_subscriber_payload)
        return make_response(200, expired_payload)

    with patch.object(client._client, "get", new=mock_get):
        result = await client.batch_check_entitlements(
            ["active_user", "expired_user", "another_expired"],
            "premium",
        )

    assert result.total == 3
    assert result.active == 1
    assert result.inactive == 2
    assert result.entitlement_identifier == "premium"


@pytest.mark.asyncio
async def test_batch_check_entitlements_api_error_counts_inactive(client):
    """API errors for individual users count as inactive, not failures."""

    async def mock_get(url, **kwargs):
        return make_response(404, {"message": "Subscriber not found"})

    with patch.object(client._client, "get", new=mock_get):
        result = await client.batch_check_entitlements(
            ["ghost_user_1", "ghost_user_2"],
            "premium",
        )

    assert result.total == 2
    assert result.active == 0
    assert result.inactive == 2
