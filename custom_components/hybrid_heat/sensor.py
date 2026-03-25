"""Diagnostic sensors mirroring engine outputs (optional but useful for dashboards)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN
from .coordinator import HybridHeatCoordinator

_LOGGER = logging.getLogger(__name__)

# (SensorEntityDescription, value_key for mapping last_decision -> state)
SENSOR_DESCRIPTIONS: tuple[tuple[SensorEntityDescription, str], ...] = (
    (
        SensorEntityDescription(
            key="active_source",
            name="Aktive Wärmequelle",
            entity_registry_enabled_default=True,
        ),
        "active_source",
    ),
    (
        SensorEntityDescription(
            key="decision_reason",
            name="Entscheidungsgrund",
            entity_registry_enabled_default=True,
        ),
        "decision_reason",
    ),
    (
        SensorEntityDescription(
            key="gas_heat_cost",
            name="Gas Wärmepreis",
            entity_registry_enabled_default=False,
        ),
        "gas_heat_cost",
    ),
    (
        SensorEntityDescription(
            key="ac_heat_cost",
            name="Klima Wärmepreis",
            entity_registry_enabled_default=False,
        ),
        "ac_heat_cost",
    ),
    (
        SensorEntityDescription(
            key="effective_electricity_price",
            name="Effektiver Strompreis",
            entity_registry_enabled_default=False,
        ),
        "effective_electricity_price",
    ),
    (
        SensorEntityDescription(
            key="cop",
            name="COP (geschätzt)",
            entity_registry_enabled_default=False,
        ),
        "cop",
    ),
    (
        SensorEntityDescription(
            key="pv_surplus_factor",
            name="PV-Überschuss-Faktor",
            entity_registry_enabled_default=False,
        ),
        "pv_surplus_factor",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HybridHeatCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        HybridHeatDiagnosticSensor(coordinator, entry, d, vk)
        for d, vk in SENSOR_DESCRIPTIONS
    )


class HybridHeatDiagnosticSensor(CoordinatorEntity[HybridHeatCoordinator], SensorEntity):
    """Engine / cost diagnostics for one room."""

    entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HybridHeatCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
        value_key: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._value_key = value_key
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_diag_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.room_config.room_name,
            manufacturer="HybridHeat",
            model="Diagnose",
        )

    @property
    def native_value(self) -> Any:
        ld = self.coordinator.last_decision
        if ld is None:
            return None
        c = ld.costs
        key = self._value_key
        if key == "active_source":
            return ld.desired_active_source
        if key == "decision_reason":
            return ld.reason
        if key == "gas_heat_cost":
            return round(c.gas_heat_cost_per_kwh, 5) if c.gas_heat_cost_per_kwh is not None else None
        if key == "ac_heat_cost":
            return round(c.ac_heat_cost_per_kwh, 5) if c.ac_heat_cost_per_kwh is not None else None
        if key == "effective_electricity_price":
            return (
                round(c.effective_electricity_price, 5)
                if c.effective_electricity_price is not None
                else None
            )
        if key == "cop":
            return round(c.cop_at_outdoor, 3) if c.cop_at_outdoor is not None else None
        if key == "pv_surplus_factor":
            return round(c.pv_surplus_factor, 3)
        return None
