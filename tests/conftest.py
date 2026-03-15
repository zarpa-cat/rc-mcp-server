"""Shared fixtures for rc-mcp-server tests."""

import pytest


@pytest.fixture
def sample_subscriber_payload() -> dict:
    return {
        "request_date": "2026-03-15T06:00:00Z",
        "request_date_ms": 1741924800000,
        "subscriber": {
            "entitlements": {
                "premium": {
                    "expires_date": "2026-04-15T06:00:00Z",
                    "grace_period_expires_date": None,
                    "product_identifier": "monthly_premium",
                    "purchase_date": "2026-03-15T06:00:00Z",
                }
            },
            "first_seen": "2026-01-01T00:00:00Z",
            "last_seen": "2026-03-15T06:00:00Z",
            "management_url": None,
            "non_subscriptions": {},
            "original_app_user_id": "test_user_123",
            "original_application_version": None,
            "original_purchase_date": None,
            "other_purchases": {},
            "subscriptions": {
                "monthly_premium": {
                    "expires_date": "2026-04-15T06:00:00Z",
                    "purchase_date": "2026-03-15T06:00:00Z",
                    "product_identifier": "monthly_premium",
                    "is_sandbox": True,
                    "unsubscribe_detected_at": None,
                    "billing_issues_detected_at": None,
                    "grace_period_expires_date": None,
                }
            },
        },
    }


@pytest.fixture
def sample_offerings_payload() -> dict:
    return {
        "current_offering_id": "default",
        "offerings": [
            {
                "identifier": "default",
                "description": "Default offering",
                "metadata": None,
                "packages": [
                    {
                        "identifier": "$rc_monthly",
                        "platform_product_identifier": "monthly_premium",
                    }
                ],
            }
        ],
    }
