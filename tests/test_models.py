"""Tests for Pydantic models."""

from datetime import UTC, datetime

from rc_mcp_server.models import (
    EntitlementCheckResult,
    EntitlementGrantResult,
    Offering,
    OfferingsResponse,
    Subscriber,
)


def test_subscriber_parse(sample_subscriber_payload):
    sub = Subscriber.model_validate(sample_subscriber_payload)
    assert sub.subscriber.original_app_user_id == "test_user_123"
    assert "premium" in sub.subscriber.entitlements
    assert "monthly_premium" in sub.subscriber.subscriptions


def test_entitlement_is_active_with_future_expiry(sample_subscriber_payload):
    sub = Subscriber.model_validate(sample_subscriber_payload)
    ent = sub.subscriber.entitlements["premium"]
    assert ent.is_active is True


def test_entitlement_is_inactive_with_past_expiry():
    from rc_mcp_server.models import Entitlement

    ent = Entitlement(
        expires_date=datetime(2020, 1, 1, tzinfo=UTC),
        product_identifier="monthly_premium",
    )
    assert ent.is_active is False


def test_entitlement_lifetime_is_active():
    from rc_mcp_server.models import Entitlement

    ent = Entitlement(expires_date=None)
    assert ent.is_active is True


def test_offerings_parse(sample_offerings_payload):
    result = OfferingsResponse(
        current_offering_id=sample_offerings_payload["current_offering_id"],
        offerings=[Offering(**o) for o in sample_offerings_payload["offerings"]],
    )
    assert result.current_offering_id == "default"
    assert len(result.offerings) == 1
    assert result.offerings[0].identifier == "default"


def test_entitlement_check_result_active():
    result = EntitlementCheckResult(
        app_user_id="user_123",
        entitlement_identifier="premium",
        is_active=True,
        expires_date=datetime(2026, 4, 15, tzinfo=UTC),
        product_identifier="monthly_premium",
    )
    assert result.is_active is True
    assert result.product_identifier == "monthly_premium"


def test_entitlement_check_result_inactive():
    result = EntitlementCheckResult(
        app_user_id="user_123",
        entitlement_identifier="premium",
        is_active=False,
    )
    assert result.is_active is False
    assert result.expires_date is None


def test_entitlement_grant_result():
    result = EntitlementGrantResult(
        app_user_id="user_123",
        entitlement_identifier="premium",
        success=True,
        message="Granted 'premium' (monthly) to user_123",
    )
    assert result.success is True
    assert "monthly" in result.message
