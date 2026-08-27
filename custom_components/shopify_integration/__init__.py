"""The Shopify Integration integration."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import ShopifyApiClient
from .const import CONF_SHOP_DOMAIN, DOMAIN
from .inventory import async_register_websocket_commands
from .coordinator import (
    ShopifyAnalyticsCoordinator,
    ShopifyMonthlyRevenueCoordinator,
    ShopifyIntegrationCoordinator,
)

PLATFORMS = [Platform.SENSOR]
FRONTEND_PATH = Path(__file__).parent / "frontend" / "shopify-inventory-card.js"
FRONTEND_URL = f"/{DOMAIN}/shopify-inventory-card.js"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the inventory frontend and WebSocket commands."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL, str(FRONTEND_PATH), False)]
    )
    async_register_websocket_commands(hass)
    return True


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
        "client": client,
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

