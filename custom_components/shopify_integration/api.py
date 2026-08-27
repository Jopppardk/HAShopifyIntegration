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
    current_month_previous_year_full: Decimal
    month_to_date_change_percent: Decimal | None
    current_month_forecast: Decimal | None
    current_month_forecast_change_percent: Decimal | None
    currency: str


@dataclass(frozen=True)
class AnalyticsData:
    """Shopify Analytics totals for the current reporting periods."""

    sessions_today: int
    sessions_month_to_date: int
    sessions_year_to_date: int
    orders_today: int
    orders_month_to_date: int
    orders_year_to_date: int
    conversion_rate_today: Decimal
    conversion_rate_month_to_date: Decimal
    conversion_rate_year_to_date: Decimal
    carts_today: int
    carts_month_to_date: int
    carts_year_to_date: int
    checkouts_reached_today: int
    checkouts_reached_month_to_date: int
    checkouts_reached_year_to_date: int
    checkouts_completed_today: int
    checkouts_completed_month_to_date: int
    checkouts_completed_year_to_date: int


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

ANALYTICS_QUERY = """
query PerformanceAnalytics($ordersQuery: String!, $sessionsQuery: String!) {
  orders: shopifyqlQuery(query: $ordersQuery) {
    tableData { rows }
    parseErrors
  }
  sessions: shopifyqlQuery(query: $sessionsQuery) {
    tableData { rows }
    parseErrors
  }
}
"""

STOCKTAKE_LOCATIONS_QUERY = """
query StocktakeLocations {
  shop { currencyCode }
  locations(first: 10) {
    nodes { id name isActive }
  }
}
"""

STOCKTAKE_ITEMS_QUERY = """
query StocktakeItems($first: Int!, $after: String, $locationId: ID!) {
  inventoryItems(first: $first, after: $after) {
    nodes {
      id
      sku
      tracked
      unitCost { amount currencyCode }
      inventoryLevel(locationId: $locationId) {
        quantities(names: ["on_hand"]) { name quantity }
      }
      variants(first: 1) {
        nodes {
          id
          title
          displayName
          barcode
          product { id title status }
        }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

SET_ON_HAND_QUERY = """
mutation SetOnHand(
  $input: InventorySetOnHandQuantitiesInput!,
  $idempotencyKey: String!
) {
  inventorySetOnHandQuantities(input: $input)
    @idempotent(key: $idempotencyKey) {
    inventoryAdjustmentGroup { id createdAt }
    userErrors { field message }
  }
}
"""

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

    async def async_get_stocktake_inventory(self) -> dict[str, Any]:
        """Return all active tracked variants at the store's only active location."""
        location_data = await self._async_graphql(STOCKTAKE_LOCATIONS_QUERY, {})
        active_locations = [
            location
            for location in location_data["locations"]["nodes"]
            if location["isActive"]
        ]
        if len(active_locations) != 1:
            raise ShopifyApiError(
                "Inventory counting requires exactly one active Shopify location"
            )
        location = active_locations[0]
        currency = str(location_data["shop"]["currencyCode"])
        items: list[dict[str, Any]] = []
        after: str | None = None

        while True:
            data = await self._async_graphql(
                STOCKTAKE_ITEMS_QUERY,
                {"first": 250, "after": after, "locationId": location["id"]},
            )
            inventory_items = data["inventoryItems"]
            for inventory_item in inventory_items["nodes"]:
                variants = inventory_item.get("variants")
                variant_nodes = variants.get("nodes", []) if variants else []
                level = inventory_item.get("inventoryLevel")
                if (
                    not inventory_item["tracked"]
                    or not variant_nodes
                    or level is None
                ):
                    continue
                variant = variant_nodes[0]
                product = variant["product"]
                if product["status"] != "ACTIVE":
                    continue
                quantities = {
                    quantity["name"]: int(quantity["quantity"])
                    for quantity in level["quantities"]
                }
                unit_cost = inventory_item.get("unitCost")
                if unit_cost is not None:
                    if unit_cost["currencyCode"] != currency:
                        raise ShopifyApiError(
                            "Inventory cost currency did not match shop currency"
                        )
                    try:
                        Decimal(unit_cost["amount"])
                    except (InvalidOperation, TypeError) as err:
                        raise ShopifyApiError(
                            "Shopify returned an invalid unit cost"
                        ) from err
                items.append(
                    {
                        "inventory_item_id": inventory_item["id"],
                        "variant_id": variant["id"],
                        "product": product["title"],
                        "variant": variant["title"],
                        "display_name": variant["displayName"],
                        "sku": inventory_item.get("sku") or "",
                        "barcode": variant.get("barcode") or "",
                        "on_hand": quantities.get("on_hand", 0),
                        "unit_cost": str(unit_cost["amount"])
                        if unit_cost is not None
                        else None,
                    }
                )

            page_info = inventory_items["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            after = page_info["endCursor"]

        items.sort(
            key=lambda item: (
                item["product"].casefold(),
                item["variant"].casefold(),
                item["sku"].casefold(),
            )
        )
        return {
            "location": {"id": location["id"], "name": location["name"]},
            "currency": currency,
            "items": items,
        }

    async def async_set_on_hand_quantities(
        self,
        location_id: str,
        updates: list[dict[str, Any]],
        idempotency_key: str,
        reference_document_uri: str,
    ) -> dict[str, Any]:
        """Set physical on-hand quantities with compare-and-set protection."""
        data = await self._async_graphql(
            SET_ON_HAND_QUERY,
            {
                "input": {
                    "reason": "correction",
                    "referenceDocumentUri": reference_document_uri,
                    "setQuantities": [
                        {
                            "inventoryItemId": update["inventory_item_id"],
                            "locationId": location_id,
                            "quantity": update["quantity"],
                            "changeFromQuantity": update["expected_quantity"],
                        }
                        for update in updates
                    ],
                },
                "idempotencyKey": idempotency_key,
            },
        )
        result = data["inventorySetOnHandQuantities"]
        return {
            "adjustment_group": result.get("inventoryAdjustmentGroup"),
            "errors": [
                {
                    "field": error.get("field"),
                    "message": str(error.get("message", "Inventory update failed")),
                }
                for error in result.get("userErrors", [])
            ],
        }

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

    async def async_get_analytics(
        self, today_key: str, month_key: str, year_key: str
    ) -> AnalyticsData:
        """Return Shopify Analytics session, order, and conversion totals."""
        orders_query = (
            "FROM sales SHOW orders WHERE sales_channel = 'Online Store' "
            "TIMESERIES day DURING this_year ORDER BY day ASC"
        )
        sessions_query = (
            "FROM sessions SHOW sessions, sessions_with_cart_additions, "
            "sessions_that_reached_checkout, sessions_that_completed_checkout "
            "WHERE human_or_bot_session = 'human' TIMESERIES day "
            "DURING this_year ORDER BY day ASC"
        )
        data = await self._async_graphql(
            ANALYTICS_QUERY,
            {"ordersQuery": orders_query, "sessionsQuery": sessions_query},
        )
        order_rows = self._shopifyql_rows(data["orders"], "orders")
        session_rows = self._shopifyql_rows(data["sessions"], "sessions")

        orders_today = orders_month = orders_year = 0
        for row in order_rows:
            day = str(row.get("day", ""))[:10]
            orders = int(Decimal(str(row.get("orders", 0))))
            if day.startswith(year_key):
                orders_year += orders
            if day.startswith(month_key):
                orders_month += orders
            if day == today_key:
                orders_today += orders

        sessions_today = sessions_month = sessions_year = 0
        checkouts_today = checkouts_month = checkouts_year = 0
        carts_today = carts_month = carts_year = 0
        reached_today = reached_month = reached_year = 0
        for row in session_rows:
            day = str(row.get("day", ""))[:10]
            sessions = int(Decimal(str(row.get("sessions", 0))))
            checkouts = int(
                Decimal(str(row.get("sessions_that_completed_checkout", 0)))
            )
            carts = int(Decimal(str(row.get("sessions_with_cart_additions", 0))))
            reached = int(
                Decimal(str(row.get("sessions_that_reached_checkout", 0)))
            )
            if day.startswith(year_key):
                sessions_year += sessions
                checkouts_year += checkouts
                carts_year += carts
                reached_year += reached
            if day.startswith(month_key):
                sessions_month += sessions
                checkouts_month += checkouts
                carts_month += carts
                reached_month += reached
            if day == today_key:
                sessions_today += sessions
                checkouts_today += checkouts
                carts_today += carts
                reached_today += reached

        def conversion_rate(completed: int, sessions: int) -> Decimal:
            if sessions == 0:
                return Decimal("0.0")
            return (
                Decimal(completed) / Decimal(sessions) * Decimal("100")
            ).quantize(Decimal("0.1"))

        return AnalyticsData(
            sessions_today,
            sessions_month,
            sessions_year,
            orders_today,
            orders_month,
            orders_year,
            conversion_rate(checkouts_today, sessions_today),
            conversion_rate(checkouts_month, sessions_month),
            conversion_rate(checkouts_year, sessions_year),
            carts_today,
            carts_month,
            carts_year,
            reached_today,
            reached_month,
            reached_year,
            checkouts_today,
            checkouts_month,
            checkouts_year,
        )

    @staticmethod
    def _shopifyql_rows(result: dict[str, Any], label: str) -> list[dict[str, Any]]:
        """Validate a ShopifyQL result and return its rows."""
        if errors := result.get("parseErrors"):
            raise ShopifyApiError(f"ShopifyQL {label} query failed: {'; '.join(errors)}")
        table = result.get("tableData")
        rows = table.get("rows") if isinstance(table, dict) else None
        if not isinstance(rows, list):
            raise ShopifyApiError(f"ShopifyQL returned no {label} data")
        return rows

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
        previous_current_month_full = previous_totals[-1]
        current_month_total = current_totals[-1]
        month_to_date_change_percent = (
            (current_month_total - previous_current_month_partial)
            / previous_current_month_partial
            * Decimal("100")
            if previous_current_month_partial != 0
            else None
        )
        current_month_forecast = (
            previous_current_month_full
            * current_month_total
            / previous_current_month_partial
            if previous_current_month_partial != 0
            else None
        )
        current_month_forecast_change_percent = (
            (current_month_forecast - previous_current_month_full)
            / previous_current_month_full
            * Decimal("100")
            if current_month_forecast is not None
            and previous_current_month_full != 0
            else None
        )
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
            months=tuple(months),
            ltm=ltm,
            previous_year=previous_year,
            change_percent=change_percent,
            current_month_previous_year_full=previous_current_month_full,
            month_to_date_change_percent=month_to_date_change_percent,
            current_month_forecast=current_month_forecast,
            current_month_forecast_change_percent=current_month_forecast_change_percent,
            currency=currency,
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

