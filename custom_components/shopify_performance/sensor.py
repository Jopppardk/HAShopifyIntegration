"""Sensors for Shopify Performance."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import RevenueData
from .const import DOMAIN
from .coordinator import ShopifyPerformanceCoordinator


@dataclass(frozen=True)
class ShopifyRevenueSensorDescription:
    """Describe a Shopify revenue sensor."""

    key: str
    translation_key: str
    value_fn: Callable[[RevenueData], Decimal]
    state_class: SensorStateClass = SensorStateClass.TOTAL


SENSORS = (
    ShopifyRevenueSensorDescription("revenue_today", "revenue_today", lambda data: data.today),
    ShopifyRevenueSensorDescription(
        "revenue_year_to_date", "revenue_year_to_date", lambda data: data.year_to_date
    ),
    ShopifyRevenueSensorDescription(
        "revenue_previous_month",
        "revenue_previous_month",
        lambda data: data.previous_month,
    ),
    ShopifyRevenueSensorDescription(
        "revenue_current_month",
        "revenue_current_month",
        lambda data: data.current_month,
    ),
    ShopifyRevenueSensorDescription(
        "revenue_last_year_same_time",
        "revenue_last_year_same_time",
        lambda data: data.last_year_same_time,
    ),
    ShopifyRevenueSensorDescription(
        "inventory_value",
        "inventory_value",
        lambda data: data.inventory_value,
        SensorStateClass.MEASUREMENT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Shopify revenue sensors."""
    coordinator: ShopifyPerformanceCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ShopifyRevenueSensor(coordinator, entry, description) for description in SENSORS
    )


class ShopifyRevenueSensor(CoordinatorEntity[ShopifyPerformanceCoordinator], SensorEntity):
    """A Shopify revenue sensor."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_icon = "mdi:cash"

    def __init__(
        self,
        coordinator: ShopifyPerformanceCoordinator,
        entry: ConfigEntry,
        description: ShopifyRevenueSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._description = description
        self._attr_translation_key = description.translation_key
        self._attr_state_class = description.state_class
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.unique_id or entry.entry_id)},
            "name": "Shopify Performance",
            "manufacturer": "Shopify",
        }

    @property
    def native_value(self) -> Decimal:
        """Return the revenue value."""
        return self._description.value_fn(self.coordinator.data)

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the shop currency."""
        return self.coordinator.data.currency

