"""Packaging reporting and durable manual entries."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import uuid4

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api import ShopifyApiClient, ShopifyApiError
from .const import DOMAIN

GET_REPORT = "shopify_integration/packaging/get"
UPSERT_MANUAL = "shopify_integration/packaging/manual/upsert"
DELETE_MANUAL = "shopify_integration/packaging/manual/delete"
SET_PRICE = "shopify_integration/packaging/price/set"
DEFAULT_PRICE_PER_KG = 3.79
STORAGE_VERSION = 1


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


def _store(hass: HomeAssistant, config_entry_id: str) -> Store[dict[str, Any]]:
    """Return the persistent packaging store for one config entry."""
    return Store(
        hass,
        STORAGE_VERSION,
        f"{DOMAIN}.packaging.{config_entry_id}",
        private=True,
        atomic_writes=True,
    )


async def _load_data(
    hass: HomeAssistant, config_entry_id: str
) -> tuple[Store[dict[str, Any]], dict[str, Any]]:
    """Load a normalized packaging store."""
    store = _store(hass, config_entry_id)
    data = await store.async_load() or {}
    data.setdefault("manual_entries", [])
    data.setdefault("snapshots", {})
    data.setdefault("price_per_kg", DEFAULT_PRICE_PER_KG)
    return store, data


def _reportable(value: Any) -> str:
    """Normalize Shopify and manual reportability values."""
    normalized = str(value or "").strip().casefold()
    if normalized in {"ja", "yes", "true", "1"}:
        return "yes"
    if normalized in {"nej", "no", "false", "0"}:
        return "no"
    return "unknown"


def _local_date(value: str) -> date:
    """Return an ISO timestamp as a Home Assistant local date."""
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        raise ShopifyApiError("Shopify returned an invalid fulfillment timestamp")
    return dt_util.as_local(parsed).date()


def _period(
    product_rows: list[dict[str, Any]],
    manual_entries: list[dict[str, Any]],
    start: date,
    end: date,
) -> dict[str, Any]:
    """Aggregate product and manual packaging for a reporting period."""
    selected_products = [
        row for row in product_rows
        if start <= date.fromisoformat(row["date"]) <= end
    ]
    selected_manual = [
        entry for entry in manual_entries
        if start <= date.fromisoformat(entry["date"]) <= end
    ]

    products: dict[str, dict[str, Any]] = {}
    unconfigured_lines = 0
    unknown_reportability_grams = 0
    for row in selected_products:
        weight = row.get("weight_grams")
        grams = int(weight) * int(row["quantity"]) if weight is not None else 0
        if weight is None:
            unconfigured_lines += 1
        status = row["reportable"]
        reportable_grams = grams if status == "yes" else 0
        if status == "unknown":
            unknown_reportability_grams += grams
        key = row.get("product_id") or row["product"]
        product = products.setdefault(
            key,
            {
                "product_id": row.get("product_id"),
                "product": row["product"],
                "grams": 0,
                "reportable_grams": 0,
                "quantity": 0,
                "orders": [],
            },
        )
        product["grams"] += grams
        product["reportable_grams"] += reportable_grams
        product["quantity"] += int(row["quantity"])
        product["orders"].append(
            {
                "order_id": row["order_id"],
                "order_name": row["order_name"],
                "date": row["date"],
                "variant": row.get("variant", ""),
                "quantity": int(row["quantity"]),
                "weight_grams": weight,
                "grams": grams,
                "reportable": status,
                "reportable_grams": reportable_grams,
            }
        )

    for product in products.values():
        product["orders"].sort(
            key=lambda row: (row["date"], row["order_name"]), reverse=True
        )

    product_grams = sum(product["grams"] for product in products.values())
    product_reportable = sum(
        product["reportable_grams"] for product in products.values()
    )
    manual_grams = sum(int(entry["weight_grams"]) for entry in selected_manual)
    manual_reportable = sum(
        int(entry["weight_grams"])
        for entry in selected_manual
        if entry["reportable"] == "yes"
    )
    unknown_reportability_grams += sum(
        int(entry["weight_grams"])
        for entry in selected_manual
        if entry["reportable"] == "unknown"
    )

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "total_grams": product_grams + manual_grams,
        "reportable_grams": product_reportable + manual_reportable,
        "product_grams": product_grams,
        "product_reportable_grams": product_reportable,
        "manual_grams": manual_grams,
        "manual_reportable_grams": manual_reportable,
        "unknown_reportability_grams": unknown_reportability_grams,
        "unconfigured_product_lines": unconfigured_lines,
        "products": sorted(
            products.values(),
            key=lambda product: (-product["grams"], product["product"].casefold()),
        ),
        "manual_entries": sorted(
            selected_manual, key=lambda entry: entry["date"], reverse=True
        ),
    }


async def _build_report(
    hass: HomeAssistant, config_entry_id: str, entry_data: dict[str, Any]
) -> dict[str, Any]:
    """Fetch Shopify data, update immutable snapshots, and build the report."""
    now = dt_util.now()
    year_start = now.replace(
        month=1, day=1, hour=0, minute=0, second=0, microsecond=0
    )
    quarter_month = ((now.month - 1) // 3) * 3 + 1
    quarter_start = year_start.replace(month=quarter_month)
    timestamp = lambda value: dt_util.as_utc(value).isoformat().replace("+00:00", "Z")

    client: ShopifyApiClient = entry_data["client"]
    live_rows = await client.async_get_packaging_fulfillments(
        timestamp(year_start), timestamp(now)
    )
    store, data = await _load_data(hass, config_entry_id)
    snapshots = data["snapshots"]
    changed = False
    active_ids: list[str] = []
    for row in live_rows:
        event_id = row["event_id"]
        active_ids.append(event_id)
        if event_id in snapshots:
            continue
        snapshots[event_id] = {
            **row,
            "date": _local_date(row["fulfilled_at"]).isoformat(),
            "reportable": _reportable(row.get("reportable")),
            "snapshotted_at": now.isoformat(),
        }
        changed = True

    if changed:
        await store.async_save(data)

    active_rows = [snapshots[event_id] for event_id in active_ids]
    today = now.date()
    return {
        "config_entry_id": config_entry_id,
        "generated_at": now.isoformat(),
        "quarter_number": (now.month - 1) // 3 + 1,
        "year": now.year,
        "price_per_kg": float(data["price_per_kg"]),
        "quarter": _period(
            active_rows, data["manual_entries"], quarter_start.date(), today
        ),
        "year_to_date": _period(
            active_rows, data["manual_entries"], year_start.date(), today
        ),
        "manual_entries": sorted(
            data["manual_entries"], key=lambda entry: entry["date"], reverse=True
        ),
    }


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): GET_REPORT,
        vol.Optional("config_entry_id"): str,
    }
)
async def websocket_get_report(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the complete packaging dashboard report."""
    try:
        config_entry_id, entry_data = _resolve_entry(
            hass, msg.get("config_entry_id")
        )
        result = await _build_report(hass, config_entry_id, entry_data)
    except (ShopifyApiError, ValueError) as err:
        connection.send_error(msg["id"], "packaging_error", str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): UPSERT_MANUAL,
        vol.Optional("config_entry_id"): str,
        vol.Optional("entry_id"): str,
        vol.Required("date"): vol.Match(r"^\d{4}-\d{2}-\d{2}$"),
        vol.Required("description"): vol.All(str, vol.Length(min=1, max=200)),
        vol.Required("supplier"): vol.All(str, vol.Length(max=200)),
        vol.Required("supplier_country"): vol.All(str, vol.Length(max=100)),
        vol.Required("supplier_cvr"): vol.All(str, vol.Length(max=50)),
        vol.Required("weight_grams"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100000000)
        ),
        vol.Required("reportable"): vol.In(["yes", "no", "unknown"]),
    }
)
async def websocket_upsert_manual(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create or update a manual packaging entry."""
    try:
        config_entry_id, _entry_data = _resolve_entry(
            hass, msg.get("config_entry_id")
        )
        entry_date = date.fromisoformat(msg["date"])
        if entry_date > dt_util.now().date():
            raise ValueError("Manual packaging entries cannot be future-dated")
        store, data = await _load_data(hass, config_entry_id)
        entry_id = msg.get("entry_id") or str(uuid4())
        entry = {
            "id": entry_id,
            "date": entry_date.isoformat(),
            "description": msg["description"].strip(),
            "supplier": msg["supplier"].strip(),
            "supplier_country": msg["supplier_country"].strip().upper(),
            "supplier_cvr": msg["supplier_cvr"].strip(),
            "weight_grams": int(msg["weight_grams"]),
            "reportable": msg["reportable"],
            "updated_at": dt_util.now().isoformat(),
        }
        entries = data["manual_entries"]
        index = next(
            (index for index, item in enumerate(entries) if item["id"] == entry_id),
            None,
        )
        if index is None:
            entries.append(entry)
        else:
            entries[index] = entry
        await store.async_save(data)
    except (ShopifyApiError, ValueError) as err:
        connection.send_error(msg["id"], "packaging_error", str(err))
        return
    connection.send_result(msg["id"], {"entry": entry})


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): DELETE_MANUAL,
        vol.Optional("config_entry_id"): str,
        vol.Required("entry_id"): str,
    }
)
async def websocket_delete_manual(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete one manual packaging entry."""
    try:
        config_entry_id, _entry_data = _resolve_entry(
            hass, msg.get("config_entry_id")
        )
        store, data = await _load_data(hass, config_entry_id)
        original_length = len(data["manual_entries"])
        data["manual_entries"] = [
            entry
            for entry in data["manual_entries"]
            if entry["id"] != msg["entry_id"]
        ]
        if len(data["manual_entries"]) == original_length:
            raise ValueError("Manual packaging entry not found")
        await store.async_save(data)
    except (ShopifyApiError, ValueError) as err:
        connection.send_error(msg["id"], "packaging_error", str(err))
        return
    connection.send_result(msg["id"], {"deleted": msg["entry_id"]})


@websocket_api.require_admin
@websocket_api.async_response
@websocket_api.websocket_command(
    {
        vol.Required("type"): SET_PRICE,
        vol.Optional("config_entry_id"): str,
        vol.Required("price_per_kg"): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=1000)
        ),
    }
)
async def websocket_set_price(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Store the estimated packaging price per reportable kilogram."""
    try:
        config_entry_id, _entry_data = _resolve_entry(
            hass, msg.get("config_entry_id")
        )
        store, data = await _load_data(hass, config_entry_id)
        data["price_per_kg"] = round(float(msg["price_per_kg"]), 4)
        await store.async_save(data)
    except (ShopifyApiError, ValueError) as err:
        connection.send_error(msg["id"], "packaging_error", str(err))
        return
    connection.send_result(
        msg["id"], {"price_per_kg": data["price_per_kg"]}
    )


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register packaging dashboard WebSocket commands."""
    websocket_api.async_register_command(hass, websocket_get_report)
    websocket_api.async_register_command(hass, websocket_upsert_manual)
    websocket_api.async_register_command(hass, websocket_delete_manual)
    websocket_api.async_register_command(hass, websocket_set_price)
