"""Config flow for Shopify Performance."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ShopifyApiClient, ShopifyAuthError, ShopifyConnectionError
from .const import CONF_SHOP_DOMAIN, DOMAIN

_SHOP_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")


def normalize_shop_domain(value: str) -> str:
    """Normalize and validate a myshopify.com hostname."""
    domain = value.strip().lower().removeprefix("https://").removeprefix("http://")
    domain = domain.rstrip("/")
    if "/" in domain or ":" in domain:
        raise ValueError("Store domain must be a hostname")
    if domain.endswith(".myshopify"):
        domain += ".com"
    if not _SHOP_RE.fullmatch(domain):
        raise ValueError("Store domain must end in .myshopify.com")
    return domain


class ShopifyPerformanceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Shopify Performance config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle initial setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                shop_domain = normalize_shop_domain(user_input[CONF_SHOP_DOMAIN])
            except ValueError:
                errors[CONF_SHOP_DOMAIN] = "invalid_shop_domain"
            else:
                await self.async_set_unique_id(shop_domain)
                self._abort_if_unique_id_configured()
                client = ShopifyApiClient(
                    async_get_clientsession(self.hass),
                    shop_domain,
                    user_input[CONF_CLIENT_ID],
                    user_input[CONF_CLIENT_SECRET],
                )
                try:
                    await client.async_validate()
                except ShopifyAuthError:
                    errors["base"] = "invalid_auth"
                except ShopifyConnectionError:
                    errors["base"] = "cannot_connect"
                except Exception:  # noqa: BLE001
                    errors["base"] = "unknown"
                else:
                    return self.async_create_entry(
                        title=shop_domain,
                        data={
                            CONF_SHOP_DOMAIN: shop_domain,
                            CONF_CLIENT_ID: user_input[CONF_CLIENT_ID],
                            CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET],
                        },
                    )

        schema = vol.Schema(
            {
                vol.Required(CONF_SHOP_DOMAIN): str,
                vol.Required(CONF_CLIENT_ID): str,
                vol.Required(CONF_CLIENT_SECRET): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

