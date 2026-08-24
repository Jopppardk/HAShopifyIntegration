"""Sensors for Shopify Integration."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import MonthlyRevenueData, RevenueData
from .const import DOMAIN
from .coordinator import (
    ShopifyMonthlyRevenueCoordinator,
    ShopifyIntegrationCoordinator,
)


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


@dataclass(frozen=True)
class ShopifyMonthlySensorDescription:
    """Describe a rolling monthly sensor."""

    key: str
    translation_key: str
    value_fn: Callable[[MonthlyRevenueData], Decimal | None]
    monetary: bool = True
    state_class: SensorStateClass = SensorStateClass.TOTAL


MONTHLY_SENSORS = (
    ShopifyMonthlySensorDescription("revenue_ltm", "revenue_ltm", lambda data: data.ltm),
    ShopifyMonthlySensorDescription(
        "revenue_ltm_previous_year",
        "revenue_ltm_previous_year",
        lambda data: data.previous_year,
    ),
    ShopifyMonthlySensorDescription(
        "revenue_ltm_change_percent",
        "revenue_ltm_change_percent",
        lambda data: (
            data.change_percent.quantize(Decimal("0.1"))
            if data.change_percent is not None
            else None
        ),
        False,
        SensorStateClass.MEASUREMENT,
    ),
    ShopifyMonthlySensorDescription(
        "monthly_revenue",
        "monthly_revenue",
        lambda data: Decimal(data.months[-1]["revenue"]),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Shopify revenue sensors."""
    coordinators = hass.data[DOMAIN][entry.entry_id]
    coordinator: ShopifyIntegrationCoordinator = coordinators["coordinator"]
    monthly_coordinator: ShopifyMonthlyRevenueCoordinator = coordinators[
        "monthly_coordinator"
    ]
    async_add_entities(
        ShopifyRevenueSensor(coordinator, entry, description) for description in SENSORS
    )
    async_add_entities(
        ShopifyMonthlySensor(monthly_coordinator, entry, description)
        for description in MONTHLY_SENSORS
    )


class ShopifyRevenueSensor(CoordinatorEntity[ShopifyIntegrationCoordinator], SensorEntity):
    """A Shopify revenue sensor."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_icon = "mdi:cash"

    def __init__(
        self,
        coordinator: ShopifyIntegrationCoordinator,
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
            "name": "Shopify Integration",
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


class ShopifyMonthlySensor(
    CoordinatorEntity[ShopifyMonthlyRevenueCoordinator], SensorEntity
):
    """A rolling monthly Shopify performance sensor."""

    _attr_icon = "mdi:chart-bar"

    def __init__(
        self,
        coordinator: ShopifyMonthlyRevenueCoordinator,
        entry: ConfigEntry,
        description: ShopifyMonthlySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._description = description
        self._attr_translation_key = description.translation_key
        self._attr_state_class = description.state_class
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        if description.monetary:
            self._attr_device_class = SensorDeviceClass.MONETARY
        else:
            self._attr_suggested_display_precision = 1
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.unique_id or entry.entry_id)},
            "name": "Shopify Integration",
            "manufacturer": "Shopify",
        }

    @property
    def native_value(self) -> Decimal | str | None:
        """Return the monthly value."""
        return self._description.value_fn(self.coordinator.data)

    @property
    def native_unit_of_measurement(self) -> str:
        """Return currency or percent."""
        if self._description.monetary:
            return self.coordinator.data.currency
        return "%"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the 12 aligned monthly comparisons on the data sensor."""
        if self._description.key != "monthly_revenue":
            return None
        return {"months": list(self.coordinator.data.months)}

