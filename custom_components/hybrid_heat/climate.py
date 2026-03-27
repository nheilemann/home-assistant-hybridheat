"""Virtual climate entity: user-facing thermostat; delegates to boiler vs heat-pump AC."""

from __future__ import annotations

import asyncio
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
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
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
    ATTR_HH_AC_CLIMATE_ENTITY,
    ATTR_HH_AC_CLIMATE_NAME,
    ATTR_HH_AC_SETPOINT_OFFSET_C,
    ATTR_HH_COP_POINTS,
    ATTR_HH_HEATING_CLIMATE_ENTITY,
    ATTR_HH_HEATING_CLIMATE_NAME,
    ATTR_HH_HEATING_EFFICIENCY,
    ATTR_HH_HYSTERESIS_C,
    ATTR_HH_MIN_IDLE_S,
    ATTR_HH_MIN_RUN_AC_S,
    ATTR_HH_MIN_RUN_HEATING_S,
    ATTR_HH_ROOM_TEMP_SENSOR_ENTITY,
    ATTR_HH_ROOM_TEMP_SENSOR_NAME,
    ATTR_HH_TEMPERATURE_INPUTS,
    ATTR_PV_SURPLUS_EXPECTED,
    DEFAULT_UPDATE_INTERVAL,
    SOURCE_AC,
    SOURCE_HEATING,
    SOURCE_NONE,
)
from .coordinator import HybridHeatCoordinator
from .engine import compute_pv_surplus_factor, decide, decide_cool, evaluate_costs
from .models import ActiveSource, CostEvaluation, DecisionResult, SnapshotInputs

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# Repeat identical climate.* calls only after this many seconds. Must be > coordinator
# poll interval or the same command is sent every refresh (many units beep on each).
_SERVICE_DEBOUNCE_S = int(DEFAULT_UPDATE_INTERVAL) + 15


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
            sw_version="0.2a22",
        )
        self._heating_id = rc.heating_climate_entity_id
        self._ac_id = rc.ac_climate_entity_id
        self._active_source: ActiveSource = SOURCE_NONE
        self._last_source_change_at: datetime | None = None
        self._source_run_started_at: datetime | None = None
        self._attr_target_temperature = 20.5
        self._attr_hvac_mode = HVACMode.HEAT
        self._extra_attrs: dict[str, Any] = {}
        self._last_mode_command: dict[str, tuple[str, float]] = {}
        self._last_temp_command: dict[str, tuple[float, float]] = {}
        self._last_turn_on_at: dict[str, float] = {}
        self._apply_children_task: asyncio.Task[None] | None = None
        self._last_child_apply_fingerprint: tuple[Any, ...] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _ac_state_changed(_event: Event) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(self.hass, [self._ac_id], _ac_state_changed)
        )

    def _ac_cool_known_unsupported(self) -> bool:
        """True only when AC state lists hvac_modes and 'cool' is not among them."""
        state = self.hass.states.get(self._ac_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return False
        modes = state.attributes.get("hvac_modes")
        if not modes:
            return False
        return not any(str(m).lower() == "cool" for m in modes)

    @property
    def hvac_modes(self) -> list[HVACMode]:
        modes = [HVACMode.OFF, HVACMode.HEAT]
        if not self._ac_cool_known_unsupported():
            modes.append(HVACMode.COOL)
        return modes

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        snap: SnapshotInputs | None = None
        if self.coordinator.data:
            raw = self.coordinator.data.get("snapshot")
            if isinstance(raw, SnapshotInputs):
                snap = raw
        merged = dict(self._extra_attrs)
        merged.update(self._room_config_and_temperature_attributes(snap))
        return merged

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
        if self._attr_hvac_mode == HVACMode.COOL:
            return HVACAction.COOLING
        return HVACAction.HEATING

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temp := kwargs.get("temperature")) is not None:
            self._attr_target_temperature = float(temp)
        self._last_child_apply_fingerprint = None
        self.async_write_ha_state()
        await self.coordinator.async_refresh()

    @staticmethod
    def _coerce_hvac_mode(mode: HVACMode | str) -> HVACMode:
        if isinstance(mode, HVACMode):
            return mode
        try:
            return HVACMode(str(mode).lower())
        except ValueError:
            return HVACMode.HEAT

    async def async_set_hvac_mode(self, hvac_mode: HVACMode | str) -> None:
        hvac_mode = self._coerce_hvac_mode(hvac_mode)
        if hvac_mode == HVACMode.COOL and self._ac_cool_known_unsupported():
            raise HomeAssistantError(
                f"The AC entity {self._ac_id} does not list HVAC mode cool.",
                translation_domain=DOMAIN,
                translation_key="ac_cool_not_supported",
                translation_placeholders={"entity_id": self._ac_id},
            )
        if hvac_mode != self._attr_hvac_mode:
            self._active_source = SOURCE_NONE
            self._last_source_change_at = None
            self._source_run_started_at = None
        self._attr_hvac_mode = hvac_mode
        self._last_child_apply_fingerprint = None
        self.async_write_ha_state()
        await self.coordinator.async_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_hvac_mode = self._coerce_hvac_mode(self._attr_hvac_mode)
        if not self.coordinator.data:
            return

        snap: SnapshotInputs = self.coordinator.data["snapshot"]
        inputs = replace(snap, target_temp_c=self._attr_target_temperature)
        gc = self.coordinator.global_config
        rc = self.coordinator.room_config
        now = dt_util.utcnow()

        _, pv_surplus_expected = compute_pv_surplus_factor(inputs, gc)
        self.coordinator.last_pv_surplus_expected = pv_surplus_expected

        if self._attr_hvac_mode == HVACMode.COOL and self._ac_cool_known_unsupported():
            _LOGGER.warning(
                "HybridHeat: Klima-Entity %s bietet keinen Modus cool — virtuelles Thermostat wechselt auf Heizen.",
                self._ac_id,
            )
            self._attr_hvac_mode = HVACMode.HEAT
            self._active_source = SOURCE_NONE
            self._last_source_change_at = None
            self._source_run_started_at = None
            self._last_child_apply_fingerprint = None

        if self._attr_hvac_mode == HVACMode.OFF:
            costs = evaluate_costs(inputs, rc, gc) or CostEvaluation()
            result = DecisionResult(
                desired_active_source=SOURCE_NONE,
                should_apply_heat=False,
                should_apply_cool=False,
                costs=costs,
                reason="HVAC AUS — keine Steuerung der Unterentities",
            )
        elif self._attr_hvac_mode == HVACMode.COOL:
            result = decide_cool(
                inputs,
                rc,
                gc,
                current_source=self._active_source,
                now=now,
                source_run_started_at=self._source_run_started_at,
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
        apply_fp = self._compute_child_apply_fingerprint(result)
        if apply_fp == self._last_child_apply_fingerprint:
            return
        if self._apply_children_task and not self._apply_children_task.done():
            self._apply_children_task.cancel()
        self._apply_children_task = self.hass.async_create_task(
            self._async_apply_to_children(result, apply_fp)
        )

    def _compute_child_apply_fingerprint(self, result: DecisionResult) -> tuple[Any, ...]:
        """If unchanged between polls, skip all climate.* services (avoids AC beeps)."""
        mode = self._coerce_hvac_mode(self._attr_hvac_mode)
        tgt = round(float(self._attr_target_temperature), 2)
        rc = self.coordinator.room_config
        t = float(self._attr_target_temperature)
        ac_heat = round(
            max(
                self._attr_min_temp,
                min(self._attr_max_temp, t + float(rc.ac_setpoint_offset_c)),
            ),
            2,
        )
        ac_cool = round(
            max(
                self._attr_min_temp,
                min(self._attr_max_temp, t - float(rc.ac_setpoint_offset_c)),
            ),
            2,
        )
        if mode == HVACMode.OFF:
            return ("off",)
        if mode == HVACMode.COOL:
            return ("cool", tgt, bool(result.should_apply_cool), ac_cool)
        return (
            "heat",
            tgt,
            bool(result.should_apply_heat),
            result.desired_active_source,
            ac_heat,
        )

    def _update_source_timestamps(self, desired: ActiveSource, now: datetime) -> None:
        prev = self._active_source
        if desired != prev:
            self._last_source_change_at = now
            self._source_run_started_at = None if desired == SOURCE_NONE else now

    @staticmethod
    def _friendly_name(hass: HomeAssistant, entity_id: str) -> str:
        state = hass.states.get(entity_id)
        if state is not None:
            fn = state.attributes.get("friendly_name")
            if isinstance(fn, str) and fn.strip():
                return fn
        return entity_id

    def _temperature_input_block(
        self,
        entity_id: str,
        value_c: float | None,
        measures_de: str,
    ) -> dict[str, Any]:
        state = self.hass.states.get(entity_id)
        unit = None
        if state is not None:
            unit = state.attributes.get("unit_of_measurement")
        return {
            "entity_id": entity_id,
            "friendly_name": self._friendly_name(self.hass, entity_id),
            "current_value_c": value_c,
            "measures": measures_de,
            "source_unit_of_measurement": unit,
        }

    def _room_config_and_temperature_attributes(
        self, snap: SnapshotInputs | None
    ) -> dict[str, Any]:
        rc = self.coordinator.room_config
        gc = self.coordinator.global_config
        inputs = snap or SnapshotInputs()
        cop_txt = ", ".join(
            f"{p.outdoor_temp_c:g}:{p.cop:g}" for p in rc.cop_points
        )
        temp_inputs = {
            "room": self._temperature_input_block(
                rc.room_temp_sensor_entity_id,
                inputs.room_temp_c,
                "Raumlufttemperatur — Regelgröße für dieses virtuelle Thermostat",
            ),
            "outdoor": self._temperature_input_block(
                gc.outdoor_temp_sensor_entity_id,
                inputs.outdoor_temp_c,
                "Außentemperatur — COP-Interpolation und Stromkosten-Heuristik",
            ),
        }
        return {
            ATTR_HH_HEATING_CLIMATE_ENTITY: rc.heating_climate_entity_id,
            ATTR_HH_HEATING_CLIMATE_NAME: self._friendly_name(
                self.hass, rc.heating_climate_entity_id
            ),
            ATTR_HH_AC_CLIMATE_ENTITY: rc.ac_climate_entity_id,
            ATTR_HH_AC_CLIMATE_NAME: self._friendly_name(self.hass, rc.ac_climate_entity_id),
            ATTR_HH_ROOM_TEMP_SENSOR_ENTITY: rc.room_temp_sensor_entity_id,
            ATTR_HH_ROOM_TEMP_SENSOR_NAME: self._friendly_name(
                self.hass, rc.room_temp_sensor_entity_id
            ),
            ATTR_HH_AC_SETPOINT_OFFSET_C: round(float(rc.ac_setpoint_offset_c), 3),
            ATTR_HH_HEATING_EFFICIENCY: rc.heating_efficiency,
            ATTR_HH_HYSTERESIS_C: rc.hysteresis_c,
            ATTR_HH_MIN_RUN_HEATING_S: rc.min_run_heating_s,
            ATTR_HH_MIN_RUN_AC_S: rc.min_run_ac_s,
            ATTR_HH_MIN_IDLE_S: rc.min_idle_after_switch_s,
            ATTR_HH_COP_POINTS: cop_txt,
            ATTR_HH_TEMPERATURE_INPUTS: temp_inputs,
        }

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

    async def _async_apply_to_children(
        self, result: DecisionResult, fingerprint: tuple[Any, ...]
    ) -> None:
        """Drive physical climates; avoid redundant service calls when possible."""
        try:
            if self._compute_child_apply_fingerprint(result) != fingerprint:
                return
            await self._async_apply_to_children_impl(result)
            self._last_child_apply_fingerprint = fingerprint
        except asyncio.CancelledError:
            raise

    async def _async_apply_to_children_impl(self, result: DecisionResult) -> None:
        if self._attr_hvac_mode == HVACMode.OFF:
            await self._async_both_off()
            return

        target = float(self._attr_target_temperature)
        rc = self.coordinator.room_config
        ac_heat_target = max(
            self._attr_min_temp,
            min(
                self._attr_max_temp,
                target + float(rc.ac_setpoint_offset_c),
            ),
        )
        ac_cool_target = max(
            self._attr_min_temp,
            min(
                self._attr_max_temp,
                target - float(rc.ac_setpoint_offset_c),
            ),
        )

        if self._attr_hvac_mode == HVACMode.COOL:
            if not result.should_apply_cool:
                await self._async_both_off()
                return
            await self._async_ensure_mode(self._heating_id, HVACMode.OFF)
            await self._async_ensure_mode(self._ac_id, HVACMode.COOL, ac_cool_target)
            return

        if not result.should_apply_heat:
            await self._async_both_off()
            return

        if result.desired_active_source == SOURCE_HEATING:
            await self._async_ensure_mode(self._ac_id, HVACMode.OFF)
            await self._async_ensure_mode(self._heating_id, HVACMode.HEAT, target)
        elif result.desired_active_source == SOURCE_AC:
            await self._async_ensure_mode(self._heating_id, HVACMode.OFF)
            await self._async_ensure_mode(self._ac_id, HVACMode.HEAT, ac_heat_target)
        else:
            await self._async_both_off()

    async def _async_both_off(self) -> None:
        await self._async_ensure_mode(self._heating_id, HVACMode.OFF)
        await self._async_ensure_mode(self._ac_id, HVACMode.OFF)

    async def _async_abort_child_if_virtual_off(self, intended: HVACMode) -> bool:
        """Return True if virtual thermostat is OFF and child heat/cool commands must stop."""
        if intended == HVACMode.OFF:
            return False
        if self._attr_hvac_mode == HVACMode.OFF:
            await self._async_both_off()
            return True
        return False

    async def _async_ensure_mode(
        self,
        entity_id: str,
        mode: HVACMode,
        temperature: float | None = None,
    ) -> None:
        if mode != HVACMode.OFF and self._attr_hvac_mode == HVACMode.OFF:
            await self._async_both_off()
            return

        state = self.hass.states.get(entity_id)
        if state is None:
            _LOGGER.warning("HybridHeat: Entity %s nicht gefunden / kein State", entity_id)
            return

        cur_mode_raw = state.state

        if mode == HVACMode.OFF:
            if cur_mode_raw not in (HVACMode.OFF, "off"):
                if self._is_recent_mode_command(entity_id, "off"):
                    return
                try:
                    await self.hass.services.async_call(
                        "climate",
                        "set_hvac_mode",
                        {"entity_id": entity_id, "hvac_mode": HVACMode.OFF},
                        blocking=False,
                    )
                    self._remember_mode_command(entity_id, "off")
                except (HomeAssistantError, ValueError) as err:
                    _LOGGER.debug("set_hvac_mode off failed %s: %s", entity_id, err)
            return

        # Only turn_on from explicit off. unknown/unavailable would re-fire every poll on
        # some integrations and causes audible beeps / IR spam.
        if cur_mode_raw in (HVACMode.OFF, "off"):
            if not self._is_recent_turn_on(entity_id):
                try:
                    await self.hass.services.async_call(
                        "climate",
                        "turn_on",
                        {"entity_id": entity_id},
                        blocking=False,
                    )
                    self._remember_turn_on(entity_id)
                except HomeAssistantError:
                    _LOGGER.debug("climate.turn_on nicht unterstützt oder fehlgeschlagen: %s", entity_id)

            if await self._async_abort_child_if_virtual_off(mode):
                return

        if mode not in (HVACMode.HEAT, HVACMode.COOL):
            return

        mode_token = mode.value
        norm_cur = str(cur_mode_raw).lower()
        if norm_cur != mode_token:
            if self._is_recent_mode_command(entity_id, mode_token):
                return
            try:
                await self.hass.services.async_call(
                    "climate",
                    "set_hvac_mode",
                    {"entity_id": entity_id, "hvac_mode": mode},
                    blocking=False,
                )
                self._remember_mode_command(entity_id, mode_token)
            except (HomeAssistantError, ValueError) as err:
                if mode == HVACMode.COOL:
                    _LOGGER.warning(
                        "HybridHeat: Kühlmodus für %s fehlgeschlagen: %s. "
                        "Prüfen Sie, ob die Entity \"cool\" unterstützt (Attribut hvac_modes).",
                        entity_id,
                        err,
                    )
                else:
                    _LOGGER.warning(
                        "HybridHeat: HVAC %s für %s fehlgeschlagen: %s",
                        mode_token,
                        entity_id,
                        err,
                    )
                return

            if await self._async_abort_child_if_virtual_off(mode):
                return

        if temperature is None:
            return

        if await self._async_abort_child_if_virtual_off(mode):
            return

        cur_sp = state.attributes.get("temperature")
        try:
            cur_tf = float(cur_sp) if cur_sp is not None else None
        except (TypeError, ValueError):
            cur_tf = None

        if cur_tf is not None and abs(cur_tf - temperature) < 0.25:
            return
        if self._is_recent_temp_command(entity_id, temperature):
            return

        try:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": entity_id, "temperature": temperature},
                blocking=False,
            )
            self._remember_temp_command(entity_id, temperature)
        except (HomeAssistantError, ValueError) as err:
            _LOGGER.warning("HybridHeat: Solltemperatur %s: %s", entity_id, err)

    def _is_recent_mode_command(self, entity_id: str, mode: str) -> bool:
        last = self._last_mode_command.get(entity_id)
        if last is None:
            return False
        last_mode, ts = last
        return last_mode == mode and (dt_util.utcnow().timestamp() - ts) < _SERVICE_DEBOUNCE_S

    def _remember_mode_command(self, entity_id: str, mode: str) -> None:
        self._last_mode_command[entity_id] = (mode, dt_util.utcnow().timestamp())

    def _is_recent_turn_on(self, entity_id: str) -> bool:
        ts = self._last_turn_on_at.get(entity_id)
        if ts is None:
            return False
        return (dt_util.utcnow().timestamp() - ts) < _SERVICE_DEBOUNCE_S

    def _remember_turn_on(self, entity_id: str) -> None:
        self._last_turn_on_at[entity_id] = dt_util.utcnow().timestamp()

    def _is_recent_temp_command(self, entity_id: str, temperature: float) -> bool:
        last = self._last_temp_command.get(entity_id)
        if last is None:
            return False
        last_temp, ts = last
        return abs(last_temp - temperature) < 0.2 and (dt_util.utcnow().timestamp() - ts) < _SERVICE_DEBOUNCE_S

    def _remember_temp_command(self, entity_id: str, temperature: float) -> None:
        self._last_temp_command[entity_id] = (float(temperature), dt_util.utcnow().timestamp())
