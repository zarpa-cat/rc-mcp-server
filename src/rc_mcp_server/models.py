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
