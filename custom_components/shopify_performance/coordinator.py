"""Data update coordinator for Shopify Performance."""

from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import RevenueData, ShopifyApiClient, ShopifyApiError
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


class ShopifyPerformanceCoordinator(DataUpdateCoordinator[RevenueData]):
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
        if current_month_start_local.month == 1:
            previous_month_start_local = current_month_start_local.replace(
                year=current_month_start_local.year - 1, month=12
            )
        else:
            previous_month_start_local = current_month_start_local.replace(
                month=current_month_start_local.month - 1
            )
        query_start_local = min(year_start_local, previous_month_start_local)

        def shopify_timestamp(value: datetime) -> str:
            return dt_util.as_utc(value).isoformat().replace("+00:00", "Z")

        try:
            return await self._client.async_get_revenue(
                shopify_timestamp(query_start_local),
                shopify_timestamp(year_start_local),
                shopify_timestamp(today_start_local),
                shopify_timestamp(previous_month_start_local),
                shopify_timestamp(current_month_start_local),
                shopify_timestamp(now_local),
            )
        except ShopifyApiError as err:
            raise UpdateFailed(str(err)) from err

