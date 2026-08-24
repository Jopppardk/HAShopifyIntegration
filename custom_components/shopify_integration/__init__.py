"""The Shopify Integration integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ShopifyApiClient
from .const import CONF_SHOP_DOMAIN, DOMAIN
from .coordinator import (
    ShopifyAnalyticsCoordinator,
    ShopifyMonthlyRevenueCoordinator,
    ShopifyIntegrationCoordinator,
)

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Shopify Integration from a config entry."""
    client = ShopifyApiClient(
        session=async_get_clientsession(hass),
        shop_domain=entry.data[CONF_SHOP_DOMAIN],
        client_id=entry.data[CONF_CLIENT_ID],
        client_secret=entry.data[CONF_CLIENT_SECRET],
    )
    coordinator = ShopifyIntegrationCoordinator(hass, client)
    analytics_coordinator = ShopifyAnalyticsCoordinator(hass, client)
    monthly_coordinator = ShopifyMonthlyRevenueCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()
    await analytics_coordinator.async_config_entry_first_refresh()
    await monthly_coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "analytics_coordinator": analytics_coordinator,
        "monthly_coordinator": monthly_coordinator,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
    return unload_ok

