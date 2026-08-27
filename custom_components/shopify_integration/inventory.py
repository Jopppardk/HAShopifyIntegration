"""WebSocket API for Shopify inventory counting."""

from __future__ import annotations

from itertools import islice
from typing import Any
from uuid import uuid4

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .api import ShopifyApiClient, ShopifyApiError
from .const import DOMAIN

GET_INVENTORY = "shopify_integration/inventory/get"
UPDATE_INVENTORY = "shopify_integration/inventory/update"
BATCH_SIZE = 100


def _chunks(values: list[dict[str, Any]], size: int):
    """Yield fixed-size chunks."""
    iterator = iter(values)
    while chunk := list(islice(iterator, size)):
        yield chunk


def _resolve_entry(
    hass: HomeAssistant, config_entry_id: str | None
) -> tuple[str, dict[str, Any]]:
    """Resolve one loaded Shopify config entry."""
    entries = hass.data.get(DOMAIN, {})
    if config_entry_id:
        entry_data = entries.get(config_entry_id)
        if entry_data is None:
            raise ShopifyApiError("The selected Shopify integration is not loaded")
        return config_entry_id, entry_data
    if len(entries) != 1:
        raise ShopifyApiError(
            "Specify config_entry_id when more than one Shopify store is configured"
        )
    return next(iter(entries.items()))


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): GET_INVENTORY,
        vol.Optional("config_entry_id"): str,
    }
)
async def websocket_get_inventory(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the complete editable stocktake list."""
    try:
        config_entry_id, entry_data = _resolve_entry(
            hass, msg.get("config_entry_id")
        )
        client: ShopifyApiClient = entry_data["client"]
        result = await client.async_get_stocktake_inventory()
    except ShopifyApiError as err:
        connection.send_error(msg["id"], "inventory_error", str(err))
        return

    result["config_entry_id"] = config_entry_id
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): UPDATE_INVENTORY,
        vol.Optional("config_entry_id"): str,
        vol.Required("updates"): vol.All(
            [
                {
                    vol.Required("inventory_item_id"): vol.Match(
                        r"^gid://shopify/InventoryItem/\d+$"
                    ),
                    vol.Required("expected_quantity"): vol.Coerce(int),
                    vol.Required("quantity"): vol.All(
                        vol.Coerce(int), vol.Range(min=0)
                    ),
                }
            ],
            vol.Length(min=1, max=5000),
        ),
    }
)
async def websocket_update_inventory(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Apply reviewed stocktake differences to Shopify."""
    try:
        config_entry_id, entry_data = _resolve_entry(
            hass, msg.get("config_entry_id")
        )
        client: ShopifyApiClient = entry_data["client"]
        inventory = await client.async_get_stocktake_inventory()
        current_by_id = {
            item["inventory_item_id"]: item for item in inventory["items"]
        }

        ready: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        seen: set[str] = set()
        for update in msg["updates"]:
            item_id = update["inventory_item_id"]
            if item_id in seen:
                conflicts.append(
                    {
                        "inventory_item_id": item_id,
                        "message": "The item was included more than once",
                    }
                )
                continue
            seen.add(item_id)
            current = current_by_id.get(item_id)
            if current is None:
                conflicts.append(
                    {
                        "inventory_item_id": item_id,
                        "message": "The item is no longer active at this location",
                    }
                )
                continue
            if current["on_hand"] != update["expected_quantity"]:
                conflicts.append(
                    {
                        "inventory_item_id": item_id,
                        "expected_quantity": update["expected_quantity"],
                        "current_quantity": current["on_hand"],
                        "requested_quantity": update["quantity"],
                        "message": "Shopify inventory changed during the count",
                    }
                )
                continue
            if update["quantity"] == update["expected_quantity"]:
                continue
            ready.append(update)

        updated: list[str] = []
        adjustment_groups: list[str] = []
        reference = f"home-assistant://{DOMAIN}/stocktake/{uuid4()}"

        for batch in _chunks(ready, BATCH_SIZE):
            result = await client.async_set_on_hand_quantities(
                inventory["location"]["id"],
                batch,
                str(uuid4()),
                reference,
            )
            if not result["errors"]:
                updated.extend(item["inventory_item_id"] for item in batch)
                if group := result["adjustment_group"]:
                    adjustment_groups.append(group["id"])
                continue

            # Retry failed batches item-by-item so one concurrent sale does not
            # prevent unrelated counted variants from being updated.
            for update in batch:
                single_result = await client.async_set_on_hand_quantities(
                    inventory["location"]["id"],
                    [update],
                    str(uuid4()),
                    reference,
                )
                if single_result["errors"]:
                    conflicts.append(
                        {
                            "inventory_item_id": update["inventory_item_id"],
                            "expected_quantity": update["expected_quantity"],
                            "requested_quantity": update["quantity"],
                            "message": "; ".join(
                                error["message"]
                                for error in single_result["errors"]
                            ),
                        }
                    )
                else:
                    updated.append(update["inventory_item_id"])
                    if group := single_result["adjustment_group"]:
                        adjustment_groups.append(group["id"])

    except ShopifyApiError as err:
        connection.send_error(msg["id"], "inventory_error", str(err))
        return

    if updated:
        hass.bus.async_fire(
            f"{DOMAIN}_inventory_updated",
            {
                "config_entry_id": config_entry_id,
                "updated_count": len(updated),
                "conflict_count": len(conflicts),
                "adjustment_group_ids": adjustment_groups,
            },
        )
        coordinator = entry_data.get("coordinator")
        if coordinator is not None:
            await coordinator.async_refresh()

    connection.send_result(
        msg["id"],
        {
            "updated": updated,
            "updated_count": len(updated),
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
        },
    )


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register inventory WebSocket commands."""
    websocket_api.async_register_command(hass, websocket_get_inventory)
    websocket_api.async_register_command(hass, websocket_update_inventory)
