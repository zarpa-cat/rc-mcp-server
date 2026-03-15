"""Pydantic models for RevenueCat API responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Entitlement(BaseModel):
    expires_date: datetime | None = None
    grace_period_expires_date: datetime | None = None
    product_identifier: str | None = None
    purchase_date: datetime | None = None

    @property
    def is_active(self) -> bool:
        if self.expires_date is None:
            return True  # lifetime
        return self.expires_date > datetime.now(self.expires_date.tzinfo)


class Subscription(BaseModel):
    expires_date: datetime | None = None
    purchase_date: datetime | None = None
    product_identifier: str | None = None
    is_sandbox: bool = False
    unsubscribe_detected_at: datetime | None = None
    billing_issues_detected_at: datetime | None = None
    grace_period_expires_date: datetime | None = None


class Subscriber(BaseModel):
    request_date: datetime | None = None
    request_date_ms: int | None = None
    subscriber: SubscriberDetail


class SubscriberDetail(BaseModel):
    entitlements: dict[str, Entitlement] = Field(default_factory=dict)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    management_url: str | None = None
    non_subscriptions: dict[str, list[Any]] = Field(default_factory=dict)
    original_app_user_id: str = ""
    original_application_version: str | None = None
    original_purchase_date: datetime | None = None
    other_purchases: dict[str, Any] = Field(default_factory=dict)
    subscriptions: dict[str, Subscription] = Field(default_factory=dict)
    subscriber_attributes: dict[str, Any] = Field(default_factory=dict)


class Offering(BaseModel):
    description: str = ""
    identifier: str = ""
    metadata: dict[str, Any] | None = None
    packages: list[dict[str, Any]] = Field(default_factory=list)


class OfferingsResponse(BaseModel):
    current_offering_id: str | None = None
    offerings: list[Offering] = Field(default_factory=list)


class EntitlementGrantResult(BaseModel):
    app_user_id: str
    entitlement_identifier: str
    success: bool
    message: str


class EntitlementCheckResult(BaseModel):
    app_user_id: str
    entitlement_identifier: str
    is_active: bool
    expires_date: datetime | None = None
    grace_period_expires_date: datetime | None = None
    product_identifier: str | None = None


class AliasResult(BaseModel):
    app_user_id: str
    alias: str
    success: bool
    message: str


class BatchEntitlementCheckResult(BaseModel):
    entitlement_identifier: str
    total: int
    active: int
    inactive: int
    results: list[EntitlementCheckResult]


class ActiveSubscriptionSummary(BaseModel):
    """Summary of a single active subscription."""

    product_identifier: str
    expires_date: datetime | None = None
    grace_period_expires_date: datetime | None = None
    billing_issues_detected_at: datetime | None = None
    unsubscribe_detected_at: datetime | None = None
    is_sandbox: bool = False

    @property
    def has_billing_issue(self) -> bool:
        return self.billing_issues_detected_at is not None

    @property
    def is_canceling(self) -> bool:
        return self.unsubscribe_detected_at is not None

    @property
    def is_in_grace_period(self) -> bool:
        if self.grace_period_expires_date is None:
            return False
        return self.grace_period_expires_date > datetime.now(
            self.grace_period_expires_date.tzinfo
        )


class SubscriptionStatus(BaseModel):
    """Agent-friendly billing summary for a subscriber."""

    app_user_id: str
    # Entitlement-level view
    active_entitlements: list[str]
    # Subscription-level view
    active_subscriptions: list[ActiveSubscriptionSummary]
    # Flags
    has_any_active: bool
    has_billing_issues: bool
    is_any_canceling: bool
    is_any_in_grace_period: bool
    # Metadata
    first_seen: datetime | None = None
    management_url: str | None = None
    # Totals
    total_subscriptions: int
    total_entitlements: int
