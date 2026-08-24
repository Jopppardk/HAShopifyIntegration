"""Data update coordinator for Shopify Integration."""

from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import MonthlyRevenueData, RevenueData, ShopifyApiClient, ShopifyApiError
from .const import DOMAIN, MONTHLY_UPDATE_INTERVAL, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


class ShopifyIntegrationCoordinator(DataUpdateCoordinator[RevenueData]):
    """Coordinate Shopify revenue updates."""

    def __init__(self, hass: HomeAssistant, client: ShopifyApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self._client = client

    async def _async_update_data(self) -> RevenueData:
        now_local = dt_util.now()
        today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        year_start_local = today_start_local.replace(month=1, day=1)
        current_month_start_local = today_start_local.replace(day=1)
        last_year_start_local = year_start_local.replace(year=year_start_local.year - 1)
        try:
            last_year_end_local = now_local.replace(year=now_local.year - 1)
        except ValueError:
            last_year_end_local = now_local.replace(year=now_local.year - 1, day=28)
        if current_month_start_local.month == 1:
            previous_month_start_local = current_month_start_local.replace(
                year=current_month_start_local.year - 1, month=12
            )
        else:
            previous_month_start_local = current_month_start_local.replace(
                month=current_month_start_local.month - 1
            )
        query_start_local = min(
            year_start_local, previous_month_start_local, last_year_start_local
        )

        def shopify_timestamp(value: datetime) -> str:
            return dt_util.as_utc(value).isoformat().replace("+00:00", "Z")

        try:
            revenue = await self._client.async_get_revenue(
                shopify_timestamp(query_start_local),
                shopify_timestamp(year_start_local),
                shopify_timestamp(today_start_local),
                shopify_timestamp(previous_month_start_local),
                shopify_timestamp(current_month_start_local),
                shopify_timestamp(current_month_start_local),
                shopify_timestamp(last_year_start_local),
                shopify_timestamp(last_year_end_local),
                shopify_timestamp(now_local),
            )
            return await self._client.async_add_inventory_value(revenue)
        except ShopifyApiError as err:
            raise UpdateFailed(str(err)) from err


def _shift_month(value: datetime, months: int) -> datetime:
    """Return the first of a local month shifted by a number of months."""
    month_index = value.year * 12 + value.month - 1 + months
    return value.replace(
        year=month_index // 12,
        month=month_index % 12 + 1,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


class ShopifyMonthlyRevenueCoordinator(DataUpdateCoordinator[MonthlyRevenueData]):
    """Coordinate the lower-frequency rolling monthly history query."""

    def __init__(self, hass: HomeAssistant, client: ShopifyApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_monthly",
            update_interval=MONTHLY_UPDATE_INTERVAL,
        )
        self._client = client

    async def _async_update_data(self) -> MonthlyRevenueData:
        now_local = dt_util.now()
        current_month = now_local.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        month_starts_local = tuple(
            _shift_month(current_month, offset) for offset in range(-23, 1)
        )
        month_starts_utc = tuple(
            dt_util.as_utc(value).isoformat().replace("+00:00", "Z")
            for value in month_starts_local
        )
        month_keys = tuple(value.strftime("%Y-%m") for value in month_starts_local)
        try:
            previous_cutoff_local = now_local.replace(year=now_local.year - 1)
        except ValueError:
            previous_cutoff_local = now_local.replace(year=now_local.year - 1, day=28)

        try:
            return await self._client.async_get_monthly_revenue(
                month_starts_utc,
                month_keys,
                dt_util.as_utc(previous_cutoff_local)
                .isoformat()
                .replace("+00:00", "Z"),
                dt_util.as_utc(now_local).isoformat().replace("+00:00", "Z"),
            )
        except ShopifyApiError as err:
            raise UpdateFailed(str(err)) from err

