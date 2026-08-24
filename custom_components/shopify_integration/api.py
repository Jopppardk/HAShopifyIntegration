"""Async Shopify Admin GraphQL API client."""

from __future__ import annotations

import asyncio
from bisect import bisect_right
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
import time
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import API_VERSION


class ShopifyApiError(Exception):
    """Base Shopify client error."""


class ShopifyAuthError(ShopifyApiError):
    """Shopify rejected the supplied credentials."""


class ShopifyConnectionError(ShopifyApiError):
    """Shopify could not be reached or returned an invalid response."""


@dataclass(frozen=True)
class RevenueData:
    """Revenue totals in the shop currency."""

    today: Decimal
    year_to_date: Decimal
    previous_month: Decimal
    current_month: Decimal
    last_year_same_time: Decimal
    inventory_value: Decimal
    currency: str


@dataclass(frozen=True)
class MonthlyRevenueData:
    """Rolling monthly revenue comparisons in the shop currency."""

    months: tuple[dict[str, Any], ...]
    ltm: Decimal
    previous_year: Decimal
    change_percent: Decimal | None
    currency: str


ORDERS_QUERY = """
query RevenueOrders($first: Int!, $after: String, $query: String!) {
  shop { currencyCode }
  orders(first: $first, after: $after, query: $query, sortKey: CREATED_AT) {
    nodes {
      createdAt
      cancelledAt
      currentTotalPriceSet { shopMoney { amount currencyCode } }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

SHOP_QUERY = "query ShopCurrency { shop { currencyCode } }"

INVENTORY_QUERY = """
query InventoryValue($first: Int!, $after: String) {
  inventoryItems(first: $first, after: $after) {
    nodes {
      id
      tracked
      unitCost { amount currencyCode }
      inventoryLevels(first: 10) {
        nodes { quantities(names: ["available"]) { name quantity } }
        pageInfo { hasNextPage endCursor }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

INVENTORY_LEVELS_QUERY = """
query InventoryLevels($id: ID!, $after: String) {
  inventoryItem(id: $id) {
    inventoryLevels(first: 250, after: $after) {
      nodes { quantities(names: ["available"]) { name quantity } }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


class ShopifyApiClient:
    """Small client with in-memory client-credentials token management."""

    def __init__(
        self,
        session: ClientSession,
        shop_domain: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        self._session = session
        self._shop_domain = shop_domain
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    @property
    def _token_url(self) -> str:
        return f"https://{self._shop_domain}/admin/oauth/access_token"

    @property
    def _graphql_url(self) -> str:
        return (
            f"https://{self._shop_domain}/admin/api/{API_VERSION}/graphql.json"
        )

    async def async_validate(self) -> str:
        """Authenticate and return the shop currency."""
        data = await self._async_graphql(SHOP_QUERY, {})
        return str(data["shop"]["currencyCode"])

    async def async_get_revenue(
        self,
        query_start_utc: str,
        year_start_utc: str,
        today_start_utc: str,
        previous_month_start_utc: str,
        previous_month_end_utc: str,
        current_month_start_utc: str,
        last_year_start_utc: str,
        last_year_end_utc: str,
        now_utc: str,
    ) -> RevenueData:
        """Fetch uncancelled orders and calculate all revenue totals."""
        after: str | None = None
        today_total = Decimal("0")
        ytd_total = Decimal("0")
        previous_month_total = Decimal("0")
        current_month_total = Decimal("0")
        last_year_same_time_total = Decimal("0")
        currency: str | None = None
        search_query = (
            f"status:any created_at:>='{query_start_utc}' created_at:<='{now_utc}'"
        )

        while True:
            data = await self._async_graphql(
                ORDERS_QUERY,
                {"first": 250, "after": after, "query": search_query},
            )
            currency = currency or str(data["shop"]["currencyCode"])
            orders = data["orders"]
            for order in orders["nodes"]:
                if order["cancelledAt"] is not None:
                    continue
                money = order["currentTotalPriceSet"]["shopMoney"]
                if money["currencyCode"] != currency:
                    raise ShopifyApiError("Order currency did not match shop currency")
                try:
                    amount = Decimal(money["amount"])
                except (InvalidOperation, TypeError) as err:
                    raise ShopifyApiError("Shopify returned an invalid amount") from err
                if order["createdAt"] >= year_start_utc:
                    ytd_total += amount
                if order["createdAt"] >= today_start_utc:
                    today_total += amount
                if (
                    previous_month_start_utc
                    <= order["createdAt"]
                    < previous_month_end_utc
                ):
                    previous_month_total += amount
                if order["createdAt"] >= current_month_start_utc:
                    current_month_total += amount
                if last_year_start_utc <= order["createdAt"] <= last_year_end_utc:
                    last_year_same_time_total += amount

            page_info = orders["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            after = page_info["endCursor"]

        if currency is None:
            raise ShopifyApiError("Shopify did not return a shop currency")
        return RevenueData(
            today_total,
            ytd_total,
            previous_month_total,
            current_month_total,
            last_year_same_time_total,
            Decimal("0"),
            currency,
        )

    async def async_add_inventory_value(self, data: RevenueData) -> RevenueData:
        """Return performance data with current available inventory at unit cost."""
        after: str | None = None
        inventory_value = Decimal("0")

        while True:
            payload = await self._async_graphql(
                INVENTORY_QUERY, {"first": 50, "after": after}
            )
            items = payload["inventoryItems"]
            for item in items["nodes"]:
                unit_cost = item["unitCost"]
                if not item["tracked"] or unit_cost is None:
                    continue
                if unit_cost["currencyCode"] != data.currency:
                    raise ShopifyApiError(
                        "Inventory cost currency did not match shop currency"
                    )
                try:
                    cost = Decimal(unit_cost["amount"])
                except (InvalidOperation, TypeError) as err:
                    raise ShopifyApiError("Shopify returned an invalid unit cost") from err

                levels = item["inventoryLevels"]
                available = self._available_quantity(levels["nodes"])
                while levels["pageInfo"]["hasNextPage"]:
                    level_payload = await self._async_graphql(
                        INVENTORY_LEVELS_QUERY,
                        {"id": item["id"], "after": levels["pageInfo"]["endCursor"]},
                    )
                    inventory_item = level_payload["inventoryItem"]
                    if inventory_item is None:
                        raise ShopifyApiError(
                            "Inventory item disappeared while updating"
                        )
                    levels = inventory_item["inventoryLevels"]
                    available += self._available_quantity(levels["nodes"])

                inventory_value += Decimal(max(available, 0)) * cost

            page_info = items["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            after = page_info["endCursor"]

        return replace(data, inventory_value=inventory_value)

    async def async_get_monthly_revenue(
        self,
        month_starts_utc: tuple[str, ...],
        month_keys: tuple[str, ...],
        previous_current_month_cutoff_utc: str,
        now_utc: str,
    ) -> MonthlyRevenueData:
        """Return rolling 12-month revenue alongside the same months a year ago."""
        if len(month_starts_utc) != 24 or len(month_keys) != 24:
            raise ValueError("Exactly 24 monthly boundaries are required")

        after: str | None = None
        totals = [Decimal("0") for _ in month_starts_utc]
        previous_current_month_partial = Decimal("0")
        currency: str | None = None
        search_query = (
            f"status:any created_at:>='{month_starts_utc[0]}' "
            f"created_at:<='{now_utc}'"
        )

        while True:
            data = await self._async_graphql(
                ORDERS_QUERY,
                {"first": 250, "after": after, "query": search_query},
            )
            currency = currency or str(data["shop"]["currencyCode"])
            orders = data["orders"]
            for order in orders["nodes"]:
                if order["cancelledAt"] is not None:
                    continue
                money = order["currentTotalPriceSet"]["shopMoney"]
                if money["currencyCode"] != currency:
                    raise ShopifyApiError("Order currency did not match shop currency")
                try:
                    amount = Decimal(money["amount"])
                except (InvalidOperation, TypeError) as err:
                    raise ShopifyApiError("Shopify returned an invalid amount") from err

                bucket = bisect_right(month_starts_utc, order["createdAt"]) - 1
                if 0 <= bucket < 24:
                    totals[bucket] += amount
                    if (
                        bucket == 11
                        and order["createdAt"] <= previous_current_month_cutoff_utc
                    ):
                        previous_current_month_partial += amount

            page_info = orders["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            after = page_info["endCursor"]

        if currency is None:
            raise ShopifyApiError("Shopify did not return a shop currency")

        current_totals = totals[12:]
        previous_totals = totals[:12]
        previous_totals[-1] = previous_current_month_partial
        months: list[dict[str, Any]] = []
        for index, (current, previous) in enumerate(
            zip(current_totals, previous_totals, strict=True)
        ):
            difference = current - previous
            percent = (
                (difference / previous * Decimal("100"))
                if previous != 0
                else None
            )
            months.append(
                {
                    "month": month_keys[index + 12],
                    "previous_month": month_keys[index],
                    "revenue": str(current),
                    "previous_year": str(previous),
                    "difference": str(difference),
                    "change_percent": str(percent.quantize(Decimal("0.01")))
                    if percent is not None
                    else None,
                    "partial": index == 11,
                }
            )

        ltm = sum(current_totals, Decimal("0"))
        previous_year = sum(previous_totals, Decimal("0"))
        change_percent = (
            (ltm - previous_year) / previous_year * Decimal("100")
            if previous_year != 0
            else None
        )
        return MonthlyRevenueData(
            tuple(months), ltm, previous_year, change_percent, currency
        )

    @staticmethod
    def _available_quantity(levels: list[dict[str, Any]]) -> int:
        """Sum available quantity from inventory level nodes."""
        return sum(
            int(quantity["quantity"])
            for level in levels
            for quantity in level["quantities"]
            if quantity["name"] == "available"
        )

    async def _async_get_token(self, force: bool = False) -> str:
        if not force and self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token

        async with self._token_lock:
            if (
                not force
                and self._access_token
                and time.monotonic() < self._token_expires_at
            ):
                return self._access_token
            try:
                response = await self._session.post(
                    self._token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                )
                if response.status in (400, 401, 403):
                    await response.read()
                    raise ShopifyAuthError("Shopify rejected the credentials")
                response.raise_for_status()
                payload = await response.json()
                token = payload.get("access_token")
                if not isinstance(token, str) or not token:
                    raise ShopifyAuthError("Shopify did not return an access token")
                expires_in = max(int(payload.get("expires_in", 0)) - 60, 0)
            except ShopifyAuthError:
                raise
            except (ClientError, ValueError, TypeError) as err:
                raise ShopifyConnectionError("Unable to obtain Shopify token") from err

            self._access_token = token
            self._token_expires_at = time.monotonic() + expires_in
            return token

    async def _async_graphql(
        self, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]:
        for attempt in range(2):
            token = await self._async_get_token(force=attempt == 1)
            try:
                response = await self._session.post(
                    self._graphql_url,
                    headers={
                        "Content-Type": "application/json",
                        "X-Shopify-Access-Token": token,
                    },
                    json={"query": query, "variables": variables},
                )
                if response.status == 401:
                    await response.read()
                    self._access_token = None
                    if attempt == 0:
                        continue
                    raise ShopifyAuthError("Shopify rejected the access token")
                if response.status == 403:
                    await response.read()
                    raise ShopifyAuthError("Shopify access scope is insufficient")
                response.raise_for_status()
                payload = await response.json()
            except ShopifyAuthError:
                raise
            except (ClientResponseError, ClientError, ValueError) as err:
                raise ShopifyConnectionError("Shopify GraphQL request failed") from err

            if errors := payload.get("errors"):
                messages = "; ".join(
                    str(error.get("message", "GraphQL error")) for error in errors
                )
                raise ShopifyApiError(messages)
            data = payload.get("data")
            if not isinstance(data, dict):
                raise ShopifyApiError("Shopify returned no GraphQL data")
            return data

        raise ShopifyAuthError("Shopify authentication failed")

