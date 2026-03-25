"""Virtual climate entity: user-facing thermostat; delegates to boiler vs heat-pump AC."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import DOMAIN
from .const import (
    ATTR_ACTIVE_SOURCE,
    ATTR_BATTERY_SOC,
    ATTR_DECISION_REASON,
    ATTR_EFFECTIVE_ELECTRICITY,
    ATTR_EST_AC_COST,
    ATTR_EST_GAS_COST,
    ATTR_PV_SURPLUS_EXPECTED,
    SOURCE_AC,
    SOURCE_HEATING,
    SOURCE_NONE,
)
from .coordinator import HybridHeatCoordinator
from .engine import compute_pv_surplus_factor, decide, evaluate_costs
from .models import ActiveSource, CostEvaluation, DecisionResult, SnapshotInputs

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HybridHeatCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HybridHeatClimate(coordinator, entry)])


class HybridHeatClimate(CoordinatorEntity[HybridHeatCoordinator], ClimateEntity):
    """Room-level hybrid thermostat (virtual)."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_min_temp = 7.0
    _attr_max_temp = 30.0

    def __init__(self, coordinator: HybridHeatCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        rc = coordinator.room_config
        self._attr_unique_id = f"{entry.entry_id}_climate"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=rc.room_name,
            manufacturer="HybridHeat",
            model="Virtuelles Hybrid-Raumthermostat",
            sw_version="0.2a8",
        )
        self._heating_id = rc.heating_climate_entity_id
        self._ac_id = rc.ac_climate_entity_id
        self._active_source: ActiveSource = SOURCE_NONE
        self._last_source_change_at: datetime | None = None
        self._source_run_started_at: datetime | None = None
        self._attr_target_temperature = 20.5
        self._attr_hvac_mode = HVACMode.HEAT
        self._extra_attrs: dict[str, Any] = {}

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._extra_attrs

    @property
    def current_temperature(self) -> float | None:
        if not self.coordinator.data:
            return None
        snap = self.coordinator.data.get("snapshot")
        if isinstance(snap, SnapshotInputs):
            return snap.room_temp_c
        return None

    @property
    def hvac_action(self) -> HVACAction | None:
        if self._attr_hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if self._active_source == SOURCE_NONE:
            return HVACAction.IDLE
        return HVACAction.HEATING

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temp := kwargs.get("temperature")) is not None:
            self._attr_target_temperature = float(temp)
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._attr_hvac_mode = hvac_mode
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        if not self.coordinator.data:
            return

        snap: SnapshotInputs = self.coordinator.data["snapshot"]
        inputs = replace(snap, target_temp_c=self._attr_target_temperature)
        gc = self.coordinator.global_config
        rc = self.coordinator.room_config
        now = dt_util.utcnow()

        _, pv_surplus_expected = compute_pv_surplus_factor(inputs, gc)
        self.coordinator.last_pv_surplus_expected = pv_surplus_expected

        if self._attr_hvac_mode == HVACMode.OFF:
            costs = evaluate_costs(inputs, rc, gc) or CostEvaluation()
            result = DecisionResult(
                desired_active_source=SOURCE_NONE,
                should_apply_heat=False,
                costs=costs,
                reason="HVAC AUS — keine Steuerung der Unterentities",
            )
        else:
            result = decide(
                inputs,
                rc,
                gc,
                current_source=self._active_source,
                now=now,
                last_source_change_at=self._last_source_change_at,
                source_run_started_at=self._source_run_started_at,
            )

        self._update_source_timestamps(result.desired_active_source, now)
        self._active_source = result.desired_active_source
        self._build_extra_attributes(result, inputs, pv_surplus_expected)
        self.coordinator.last_decision = result

        self.async_write_ha_state()
        self.hass.async_create_task(self._async_apply_to_children(result))

    def _update_source_timestamps(self, desired: ActiveSource, now: datetime) -> None:
        prev = self._active_source
        if desired != prev:
            self._last_source_change_at = now
            self._source_run_started_at = None if desired == SOURCE_NONE else now

    def _build_extra_attributes(
        self,
        result: DecisionResult,
        inputs: SnapshotInputs,
        pv_surplus_expected: bool,
    ) -> None:
        c = result.costs
        self._extra_attrs = {
            ATTR_ACTIVE_SOURCE: self._active_source,
            ATTR_EST_GAS_COST: c.gas_heat_cost_per_kwh,
            ATTR_EST_AC_COST: c.ac_heat_cost_per_kwh,
            ATTR_EFFECTIVE_ELECTRICITY: c.effective_electricity_price,
            ATTR_PV_SURPLUS_EXPECTED: pv_surplus_expected,
            ATTR_BATTERY_SOC: inputs.battery_soc_pct,
            ATTR_DECISION_REASON: result.reason,
        }

    async def _async_apply_to_children(self, result: DecisionResult) -> None:
        """Drive physical climates; avoid redundant service calls when possible."""
        if self._attr_hvac_mode == HVACMode.OFF:
            await self._async_both_off()
            return

        if not result.should_apply_heat:
            await self._async_both_off()
            return

        target = self._attr_target_temperature
        if result.desired_active_source == SOURCE_HEATING:
            await self._async_ensure_mode(self._ac_id, HVACMode.OFF)
            await self._async_ensure_mode(self._heating_id, HVACMode.HEAT, target)
        elif result.desired_active_source == SOURCE_AC:
            await self._async_ensure_mode(self._heating_id, HVACMode.OFF)
            await self._async_ensure_mode(self._ac_id, HVACMode.HEAT, target)
        else:
            await self._async_both_off()

    async def _async_both_off(self) -> None:
        await self._async_ensure_mode(self._heating_id, HVACMode.OFF)
        await self._async_ensure_mode(self._ac_id, HVACMode.OFF)

    async def _async_ensure_mode(
        self,
        entity_id: str,
        mode: HVACMode,
        temperature: float | None = None,
    ) -> None:
        state = self.hass.states.get(entity_id)
        if state is None:
            _LOGGER.warning("HybridHeat: Entity %s nicht gefunden / kein State", entity_id)
            return

        cur_mode_raw = state.state

        if mode == HVACMode.OFF:
            if cur_mode_raw not in (HVACMode.OFF, "off"):
                try:
                    await self.hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {"entity_id": entity_id, "hvac_mode": HVACMode.OFF},
                        blocking=False,
                    )
                except (HomeAssistantError, ValueError) as err:
                    _LOGGER.debug("set_hvac_mode off failed %s: %s", entity_id, err)
            return

        if cur_mode_raw in (HVACMode.OFF, "off", "unknown", "unavailable"):
            try:
                await self.hass.services.async_call(
                    "climate",
                    "turn_on",
                    {"entity_id": entity_id},
                    blocking=False,
                )
            except HomeAssistantError:
                _LOGGER.debug("climate.turn_on nicht unterstützt oder fehlgeschlagen: %s", entity_id)

        if cur_mode_raw != HVACMode.HEAT:
            try:
                await self.hass.services.async_call(
                    "climate",
                    "set_hvac_mode",
                    {"entity_id": entity_id, "hvac_mode": HVACMode.HEAT},
                    blocking=False,
                )
            except (HomeAssistantError, ValueError) as err:
                _LOGGER.warning("HybridHeat: HVAC heat für %s fehlgeschlagen: %s", entity_id, err)
                return

        if temperature is None:
            return

        cur_sp = state.attributes.get("temperature")
        try:
            cur_tf = float(cur_sp) if cur_sp is not None else None
        except (TypeError, ValueError):
            cur_tf = None

        if cur_tf is not None and abs(cur_tf - temperature) < 0.25:
            return

        try:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": entity_id, "temperature": temperature},
                blocking=False,
            )
        except (HomeAssistantError, ValueError) as err:
            _LOGGER.warning("HybridHeat: Solltemperatur %s: %s", entity_id, err)
