"""RevenueCat REST API v1 client."""

from __future__ import annotations

import asyncio
import os

import httpx

from .models import (
    AliasResult,
    BatchEntitlementCheckResult,
    EntitlementCheckResult,
    EntitlementGrantResult,
    Offering,
    OfferingsResponse,
    Subscriber,
)

RC_BASE_URL = "https://api.revenuecat.com"
_DEFAULT_TIMEOUT = 15.0


class RCError(Exception):
    """RevenueCat API error."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(f"RC API {status}: {message}")


class RCClient:
    """Thin async wrapper around the RevenueCat REST API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = RC_BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.api_key = api_key or os.environ.get("REVENUECAT_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "RevenueCat API key required. Set REVENUECAT_API_KEY env var."
            )
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=timeout,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> RCClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_error:
            try:
                body = response.json()
                message = body.get("message", response.text)
            except Exception:
                message = response.text
            raise RCError(response.status_code, message)

    # ── Subscribers ──────────────────────────────────────────────────────────

    async def get_subscriber(self, app_user_id: str) -> Subscriber:
        """Fetch full subscriber info including entitlements and subscriptions."""
        r = await self._client.get(f"/v1/subscribers/{app_user_id}")
        self._raise_for_status(r)
        return Subscriber.model_validate(r.json())

    async def delete_subscriber(self, app_user_id: str) -> dict:
        """Delete a subscriber and all their purchase info."""
        r = await self._client.delete(f"/v1/subscribers/{app_user_id}")
        self._raise_for_status(r)
        return r.json()

    # ── Entitlements ─────────────────────────────────────────────────────────

    async def grant_promotional_entitlement(
        self,
        app_user_id: str,
        entitlement_identifier: str,
        duration: str = "lifetime",
        start_time_ms: int | None = None,
    ) -> EntitlementGrantResult:
        """Grant a promotional entitlement to a subscriber.

        duration options: daily, weekly, monthly, two_month, three_month,
                          six_month, yearly, lifetime
        """
        payload: dict = {"duration": duration}
        if start_time_ms is not None:
            payload["start_time_ms"] = start_time_ms

        r = await self._client.post(
            f"/v1/subscribers/{app_user_id}/entitlements/{entitlement_identifier}/promotional",
            json=payload,
        )
        self._raise_for_status(r)
        return EntitlementGrantResult(
            app_user_id=app_user_id,
            entitlement_identifier=entitlement_identifier,
            success=True,
            message=f"Granted '{entitlement_identifier}' ({duration}) to {app_user_id}",
        )

    async def revoke_promotional_entitlements(
        self,
        app_user_id: str,
        entitlement_identifier: str,
    ) -> EntitlementGrantResult:
        """Revoke all promotional entitlements for a given identifier."""
        r = await self._client.delete(
            f"/v1/subscribers/{app_user_id}/entitlements/{entitlement_identifier}/promotional",
        )
        self._raise_for_status(r)
        return EntitlementGrantResult(
            app_user_id=app_user_id,
            entitlement_identifier=entitlement_identifier,
            success=True,
            message=f"Revoked '{entitlement_identifier}' from {app_user_id}",
        )

    async def check_entitlement(
        self,
        app_user_id: str,
        entitlement_identifier: str,
    ) -> EntitlementCheckResult:
        """Check if a subscriber has a given entitlement active."""
        sub = await self.get_subscriber(app_user_id)
        ent = sub.subscriber.entitlements.get(entitlement_identifier)
        if ent is None:
            return EntitlementCheckResult(
                app_user_id=app_user_id,
                entitlement_identifier=entitlement_identifier,
                is_active=False,
            )
        return EntitlementCheckResult(
            app_user_id=app_user_id,
            entitlement_identifier=entitlement_identifier,
            is_active=ent.is_active,
            expires_date=ent.expires_date,
            grace_period_expires_date=ent.grace_period_expires_date,
            product_identifier=ent.product_identifier,
        )

    # ── Offerings ─────────────────────────────────────────────────────────────

    async def get_offerings(self, app_user_id: str) -> OfferingsResponse:
        """Fetch offerings for a subscriber."""
        r = await self._client.get(f"/v1/subscribers/{app_user_id}/offerings")
        self._raise_for_status(r)
        data = r.json()
        offerings = [
            Offering(
                identifier=o.get("identifier", ""),
                description=o.get("description", ""),
                metadata=o.get("metadata"),
                packages=o.get("packages", []),
            )
            for o in data.get("offerings", [])
        ]
        return OfferingsResponse(
            current_offering_id=data.get("current_offering_id"),
            offerings=offerings,
        )

    # ── Attributes ────────────────────────────────────────────────────────────

    async def set_attributes(
        self,
        app_user_id: str,
        attributes: dict[str, str | None],
    ) -> dict:
        """Set subscriber attributes (key/value pairs, value=None to delete)."""
        payload = {"attributes": {k: {"value": v} for k, v in attributes.items()}}
        r = await self._client.post(
            f"/v1/subscribers/{app_user_id}/attributes",
            json=payload,
        )
        self._raise_for_status(r)
        return {"success": True, "app_user_id": app_user_id, "attributes": attributes}

    async def get_attributes(self, app_user_id: str) -> dict[str, str | None]:
        """Fetch subscriber attributes (key/value pairs).

        Returns a clean dict of {key: value}. value may be None if unset.
        """
        sub = await self.get_subscriber(app_user_id)
        raw: dict = getattr(sub.subscriber, "subscriber_attributes", {}) or {}
        # RC returns {"key": {"value": "...", "updated_at_ms": ...}}
        return {k: v.get("value") if isinstance(v, dict) else v for k, v in raw.items()}

    # ── Aliases ───────────────────────────────────────────────────────────────

    async def create_alias(
        self,
        app_user_id: str,
        new_app_user_id: str,
    ) -> AliasResult:
        """Create an alias linking new_app_user_id to the existing subscriber.

        Useful for account linking: associate an anonymous ID with an identified user.
        """
        r = await self._client.post(
            f"/v1/subscribers/{app_user_id}/aliases",
            json={"new_app_user_id": new_app_user_id},
        )
        self._raise_for_status(r)
        return AliasResult(
            app_user_id=app_user_id,
            alias=new_app_user_id,
            success=True,
            message=f"Alias '{new_app_user_id}' linked to '{app_user_id}'",
        )

    # ── Batch ─────────────────────────────────────────────────────────────────

    async def batch_check_entitlements(
        self,
        app_user_ids: list[str],
        entitlement_identifier: str,
        max_concurrency: int = 5,
    ) -> BatchEntitlementCheckResult:
        """Check an entitlement for multiple subscribers in parallel.

        Returns an aggregate summary plus per-subscriber results.
        max_concurrency limits parallel RC API calls.
        """
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _check(uid: str) -> EntitlementCheckResult:
            async with semaphore:
                try:
                    return await self.check_entitlement(uid, entitlement_identifier)
                except RCError:
                    return EntitlementCheckResult(
                        app_user_id=uid,
                        entitlement_identifier=entitlement_identifier,
                        is_active=False,
                    )

        results = await asyncio.gather(*[_check(uid) for uid in app_user_ids])
        active = sum(1 for r in results if r.is_active)
        return BatchEntitlementCheckResult(
            entitlement_identifier=entitlement_identifier,
            total=len(results),
            active=active,
            inactive=len(results) - active,
            results=list(results),
        )
