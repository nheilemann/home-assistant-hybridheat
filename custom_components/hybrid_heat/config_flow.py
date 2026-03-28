"""Config flow for HybridHeat (UI-based setup)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_AC_CLIMATE,
    CONF_AC_SETPOINT_OFFSET,
    CONF_BASE_LOAD_W,
    CONF_BATTERY_CAPACITY_KWH,
    CONF_BATTERY_MAX_SOC,
    CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_SOC_SENSOR,
    CONF_COP_POINTS,
    CONF_ELECTRICITY_PRICE_PER_KWH,
    CONF_ELECTRICITY_PRICE_SENSOR,
    CONF_FEED_IN_PRICE_PER_KWH,
    CONF_FEED_IN_SENSOR,
    CONF_FORECAST_SOLAR_ENTITIES,
    CONF_GAS_PRICE_PER_KWH,
    CONF_GAS_PRICE_SENSOR,
    CONF_HEATING_CLIMATE,
    CONF_HEATING_EFFICIENCY,
    CONF_HOUSE_POWER_ENTITY,
    CONF_HYSTERESIS,
    CONF_MIN_IDLE,
    CONF_MIN_RUN_AC,
    CONF_MIN_RUN_HEATING,
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_ROOM_NAME,
    CONF_ROOM_TEMP_SENSOR,
    DEFAULT_ELECTRICITY_PRICE_PER_KWH,
    DEFAULT_FEED_IN_PRICE_PER_KWH,
    DEFAULT_GAS_PRICE_PER_KWH,
    DEFAULT_HEATING_EFFICIENCY,
    DEFAULT_HYSTERESIS,
    DEFAULT_MIN_IDLE,
    DEFAULT_MIN_RUN_AC,
    DEFAULT_MIN_RUN_HEATING,
    DEFAULT_AC_SETPOINT_OFFSET,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

SHARED_OPTION_KEYS: tuple[str, ...] = (
    CONF_OUTDOOR_TEMP_SENSOR,
    CONF_ELECTRICITY_PRICE_PER_KWH,
    CONF_GAS_PRICE_PER_KWH,
    CONF_FEED_IN_PRICE_PER_KWH,
    CONF_FORECAST_SOLAR_ENTITIES,
    CONF_BATTERY_CAPACITY_KWH,
    CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_MAX_SOC,
    CONF_BASE_LOAD_W,
    CONF_HEATING_EFFICIENCY,
    CONF_HYSTERESIS,
    CONF_MIN_RUN_HEATING,
    CONF_MIN_RUN_AC,
    CONF_MIN_IDLE,
    CONF_COP_POINTS,
)


def globals_form_values_from_merged_data(d: dict[str, Any]) -> dict[str, Any]:
    """Build globals form defaults from merged config entry data + options."""
    out: dict[str, Any] = {}

    forecast = d.get(CONF_FORECAST_SOLAR_ENTITIES, [])
    if isinstance(forecast, str):
        out[CONF_FORECAST_SOLAR_ENTITIES] = [forecast] if forecast else []
    elif isinstance(forecast, tuple):
        out[CONF_FORECAST_SOLAR_ENTITIES] = list(forecast)
    elif isinstance(forecast, list):
        out[CONF_FORECAST_SOLAR_ENTITIES] = forecast
    else:
        out[CONF_FORECAST_SOLAR_ENTITIES] = []

    for key, fallback in (
        (CONF_ELECTRICITY_PRICE_PER_KWH, DEFAULT_ELECTRICITY_PRICE_PER_KWH),
        (CONF_GAS_PRICE_PER_KWH, DEFAULT_GAS_PRICE_PER_KWH),
        (CONF_FEED_IN_PRICE_PER_KWH, DEFAULT_FEED_IN_PRICE_PER_KWH),
        (CONF_BATTERY_CAPACITY_KWH, 0.0),
        (CONF_BATTERY_MIN_SOC, 15.0),
        (CONF_BATTERY_MAX_SOC, 95.0),
        (CONF_BASE_LOAD_W, 400.0),
        (CONF_HEATING_EFFICIENCY, DEFAULT_HEATING_EFFICIENCY),
        (CONF_HYSTERESIS, DEFAULT_HYSTERESIS),
        (CONF_AC_SETPOINT_OFFSET, DEFAULT_AC_SETPOINT_OFFSET),
    ):
        raw = d.get(key, fallback)
        try:
            out[key] = float(raw)
        except (TypeError, ValueError):
            out[key] = float(fallback)

    for key, fallback in (
        (CONF_MIN_RUN_HEATING, DEFAULT_MIN_RUN_HEATING),
        (CONF_MIN_RUN_AC, DEFAULT_MIN_RUN_AC),
        (CONF_MIN_IDLE, DEFAULT_MIN_IDLE),
    ):
        raw = d.get(key, fallback)
        try:
            out[key] = int(raw)
        except (TypeError, ValueError):
            out[key] = int(fallback)

    out[CONF_OUTDOOR_TEMP_SENSOR] = d.get(CONF_OUTDOOR_TEMP_SENSOR)

    cop_raw = d.get(CONF_COP_POINTS, "")
    if isinstance(cop_raw, str):
        out[CONF_COP_POINTS] = cop_raw
    elif isinstance(cop_raw, list):
        parts: list[str] = []
        for item in cop_raw:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                parts.append(f"{item[0]}:{item[1]}")
            elif isinstance(item, dict):
                t = item.get("t", item.get("outdoor_temp_c"))
                c = item.get("cop")
                if t is not None and c is not None:
                    parts.append(f"{t}:{c}")
        out[CONF_COP_POINTS] = ", ".join(parts)
    else:
        out[CONF_COP_POINTS] = ""

    return out


def _globals_suggestions_for_additional_room(hass: HomeAssistant) -> dict[str, Any]:
    """Pre-fill globals step from an existing HybridHeat room (shared prices/sensors)."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return {}
    sibling = entries[-1]
    merged = {**dict(sibling.data), **dict(sibling.options)}
    out = globals_form_values_from_merged_data(merged)
    out.pop(CONF_AC_SETPOINT_OFFSET, None)
    return out


def _inherit_globals_not_in_form(
    hass: HomeAssistant, normalized: dict[str, Any]
) -> None:
    """Copy battery SoC / house power from a sibling entry (not in initial setup form)."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return
    sibling = entries[-1]
    td = {**dict(sibling.data), **dict(sibling.options)}
    for key in (CONF_BATTERY_SOC_SENSOR, CONF_HOUSE_POWER_ENTITY):
        if normalized.get(key):
            continue
        val = td.get(key)
        if val not in (None, "", "unknown"):
            normalized[key] = val


def _climate_selector(multiple: bool = False) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="climate", multiple=multiple)
    )


def _sensor_selector(multiple: bool = False) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor", multiple=multiple)
    )


def _ac_cool_known_unsupported(hass: HomeAssistant, entity_id: str) -> bool:
    """True when AC state reports hvac_modes and 'cool' is not included (setup may reject)."""
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable"):
        return False
    modes = state.attributes.get("hvac_modes")
    if not modes:
        return False
    return not any(str(m).lower() == "cool" for m in modes)


class HybridHeatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[misc]
    """Handle a config flow for HybridHeat (one config entry = one room)."""

    VERSION = 1

    def __init__(self) -> None:
        self._room_data: dict[str, Any] = {}
        self._room_data_pending: dict[str, Any] | None = None
        self._reconfigure_pending: dict[str, Any] | None = None

    @callback
    def _complete_reconfigure(
        self,
        entry: config_entries.ConfigEntry,
        room_input: dict[str, Any],
    ) -> config_entries.ConfigFlowResult:
        """Apply room fields to the existing config entry and reload."""
        room_name = str(room_input[CONF_ROOM_NAME]).strip()
        new_uid = f"{DOMAIN}_{room_name.lower().replace(' ', '_')}"
        if new_uid != (entry.unique_id or ""):
            for other in self.hass.config_entries.async_entries(DOMAIN):
                if other.entry_id != entry.entry_id and other.unique_id == new_uid:
                    return self.async_show_form(
                        step_id="reconfigure",
                        data_schema=self.add_suggested_values_to_schema(
                            self._build_user_schema(), room_input
                        ),
                        errors={"base": "room_name_taken"},
                    )
        return self.async_update_reload_and_abort(
            entry,
            unique_id=new_uid,
            title=room_name,
            data_updates={
                CONF_ROOM_NAME: room_name,
                CONF_HEATING_CLIMATE: room_input[CONF_HEATING_CLIMATE],
                CONF_AC_CLIMATE: room_input[CONF_AC_CLIMATE],
                CONF_ROOM_TEMP_SENSOR: room_input[CONF_ROOM_TEMP_SENSOR],
            },
        )

    def _build_user_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_ROOM_NAME): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.TEXT,
                    )
                ),
                vol.Required(CONF_HEATING_CLIMATE): _climate_selector(),
                vol.Required(CONF_AC_CLIMATE): _climate_selector(),
                vol.Required(CONF_ROOM_TEMP_SENSOR): _sensor_selector(),
            },
            extra=vol.REMOVE_EXTRA,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: room identity and room-bound climates / sensor."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                room_name = str(user_input.get(CONF_ROOM_NAME, "")).strip()
                heat_ent = user_input.get(CONF_HEATING_CLIMATE)
                ac_ent = user_input.get(CONF_AC_CLIMATE)
                if not room_name:
                    errors["base"] = "empty_room_name"
                elif heat_ent == ac_ent:
                    errors["base"] = "same_climate_entities"
                elif isinstance(ac_ent, str) and _ac_cool_known_unsupported(
                    self.hass, ac_ent
                ):
                    self._room_data_pending = user_input
                    return self.async_show_menu(
                        step_id="confirm_ac_no_cool",
                        menu_options=["choose_other_ac", "continue_without_cool"],
                        description_placeholders={"ac_entity": ac_ent},
                    )
                else:
                    unique_id = f"{DOMAIN}_{room_name.lower().replace(' ', '_')}"
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                    self._room_data = user_input
                    return await self.async_step_globals()
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "HybridHeat: async_step_user failed: %s",
                    err,
                    exc_info=True,
                )
                errors["base"] = "unknown"

        try:
            schema = self._build_user_schema()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("HybridHeat: building user-step schema failed")
            return self.async_abort(reason="unknown")

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Change room name, heating/AC climates, and room temperature sensor."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                room_name = str(user_input.get(CONF_ROOM_NAME, "")).strip()
                heat_ent = user_input.get(CONF_HEATING_CLIMATE)
                ac_ent = user_input.get(CONF_AC_CLIMATE)
                if not room_name:
                    errors["base"] = "empty_room_name"
                elif heat_ent == ac_ent:
                    errors["base"] = "same_climate_entities"
                elif isinstance(ac_ent, str) and _ac_cool_known_unsupported(
                    self.hass, ac_ent
                ):
                    self._reconfigure_pending = user_input
                    return self.async_show_menu(
                        step_id="reconfigure_ac_no_cool",
                        menu_options=[
                            "reconfigure_choose_other_ac",
                            "reconfigure_continue_without_cool",
                        ],
                        description_placeholders={"ac_entity": ac_ent},
                    )
                else:
                    return self._complete_reconfigure(entry, user_input)
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "HybridHeat: async_step_reconfigure failed: %s",
                    err,
                    exc_info=True,
                )
                errors["base"] = "unknown"

        merged = {**dict(entry.data), **dict(entry.options)}
        suggested: dict[str, Any] = {
            CONF_ROOM_NAME: merged.get(CONF_ROOM_NAME, ""),
            CONF_HEATING_CLIMATE: merged.get(CONF_HEATING_CLIMATE),
            CONF_AC_CLIMATE: merged.get(CONF_AC_CLIMATE),
            CONF_ROOM_TEMP_SENSOR: merged.get(CONF_ROOM_TEMP_SENSOR),
        }
        if user_input is not None and errors:
            suggested.update(user_input)

        try:
            schema = self._build_user_schema()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("HybridHeat: building reconfigure schema failed")
            return self.async_abort(reason="unknown")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    async def async_step_reconfigure_choose_other_ac(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Reconfigure menu: return to room form with previous values."""
        pending = self._reconfigure_pending
        self._reconfigure_pending = None
        try:
            schema = self._build_user_schema()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("HybridHeat: building reconfigure schema failed")
            return self.async_abort(reason="unknown")
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(schema, pending or {}),
            errors={},
        )

    async def async_step_reconfigure_continue_without_cool(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Reconfigure menu: accept AC without cool in hvac_modes."""
        entry = self._get_reconfigure_entry()
        pending = self._reconfigure_pending
        self._reconfigure_pending = None
        if not pending:
            return self.async_abort(reason="unknown")
        room_name = str(pending.get(CONF_ROOM_NAME, "")).strip()
        heat_ent = pending.get(CONF_HEATING_CLIMATE)
        ac_ent = pending.get(CONF_AC_CLIMATE)
        if not room_name or heat_ent == ac_ent:
            return self.async_abort(reason="unknown")
        if isinstance(ac_ent, str):
            _LOGGER.info(
                "HybridHeat: Reconfigure ohne Kühlmodus (AC %s: kein cool in hvac_modes).",
                ac_ent,
            )
        return self._complete_reconfigure(entry, pending)

    async def async_step_choose_other_ac(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Menu: go back to room step and keep entered values."""
        pending = self._room_data_pending
        self._room_data_pending = None
        try:
            schema = self._build_user_schema()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("HybridHeat: building user-step schema failed")
            return self.async_abort(reason="unknown")
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, pending or {}),
            errors={},
        )

    async def async_step_continue_without_cool(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Menu: accept AC without cool in hvac_modes (heat-only virtual cool)."""
        pending = self._room_data_pending
        self._room_data_pending = None
        if not pending:
            return self.async_abort(reason="unknown")
        room_name = str(pending.get(CONF_ROOM_NAME, "")).strip()
        heat_ent = pending.get(CONF_HEATING_CLIMATE)
        ac_ent = pending.get(CONF_AC_CLIMATE)
        if not room_name or heat_ent == ac_ent:
            return self.async_abort(reason="unknown")
        unique_id = f"{DOMAIN}_{room_name.lower().replace(' ', '_')}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        self._room_data = pending
        if isinstance(ac_ent, str):
            _LOGGER.info(
                "HybridHeat: Einrichtung ohne Kühlmodus (AC %s: kein cool in hvac_modes).",
                ac_ent,
            )
        return await self.async_step_globals()

    async def async_step_globals(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: global sensors, economics, stability, optional battery/load/COP text."""
        errors: dict[str, str] = {}
        template_globals = _globals_suggestions_for_additional_room(self.hass)

        if user_input is not None:
            try:
                data = {**self._room_data, **user_input}
                try:
                    normalized = _normalize_entry(data)
                except ValueError:
                    errors["base"] = "forecast_required"
                else:
                    _inherit_globals_not_in_form(self.hass, normalized)
                    return self.async_create_entry(
                        title=normalized[CONF_ROOM_NAME], data=normalized
                    )
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "HybridHeat: async_step_globals submit failed: %s",
                    err,
                    exc_info=True,
                )
                errors["base"] = "unknown"

        suggested = dict(template_globals)
        if user_input is not None and errors:
            suggested.update(user_input)

        try:
            schema = vol.Schema(
                {
                    vol.Required(CONF_OUTDOOR_TEMP_SENSOR): _sensor_selector(),
                    vol.Required(
                        CONF_ELECTRICITY_PRICE_PER_KWH,
                        default=DEFAULT_ELECTRICITY_PRICE_PER_KWH,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                            min=0,
                            max=5,
                            step=0.001,
                            unit_of_measurement="€/kWh",
                        )
                    ),
                    vol.Required(
                        CONF_GAS_PRICE_PER_KWH,
                        default=DEFAULT_GAS_PRICE_PER_KWH,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                            min=0,
                            max=5,
                            step=0.001,
                            unit_of_measurement="€/kWh",
                        )
                    ),
                    vol.Required(
                        CONF_FEED_IN_PRICE_PER_KWH,
                        default=DEFAULT_FEED_IN_PRICE_PER_KWH,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                            min=0,
                            max=5,
                            step=0.001,
                            unit_of_measurement="€/kWh",
                        )
                    ),
                    vol.Required(CONF_FORECAST_SOLAR_ENTITIES): _sensor_selector(
                        multiple=True
                    ),
                    vol.Optional(
                        CONF_BATTERY_CAPACITY_KWH,
                        default=0,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                            min=0,
                            max=200,
                            step=0.1,
                            unit_of_measurement="kWh",
                        )
                    ),
                    vol.Optional(
                        CONF_BATTERY_MIN_SOC,
                        default=15,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                            min=0,
                            max=100,
                            step=1,
                            unit_of_measurement="%",
                        )
                    ),
                    vol.Optional(
                        CONF_BATTERY_MAX_SOC,
                        default=95,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                            min=0,
                            max=100,
                            step=1,
                            unit_of_measurement="%",
                        )
                    ),
                    vol.Optional(
                        CONF_BASE_LOAD_W,
                        default=400,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                            min=0,
                            max=20000,
                            step=50,
                            unit_of_measurement="W",
                        )
                    ),
                    vol.Optional(
                        CONF_HEATING_EFFICIENCY,
                        default=DEFAULT_HEATING_EFFICIENCY,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                            min=0.5,
                            max=1.0,
                            step=0.01,
                        )
                    ),
                    vol.Optional(
                        CONF_HYSTERESIS,
                        default=DEFAULT_HYSTERESIS,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                            min=0.1,
                            max=3.0,
                            step=0.05,
                            unit_of_measurement="°C",
                        )
                    ),
                    vol.Optional(
                        CONF_MIN_RUN_HEATING,
                        default=DEFAULT_MIN_RUN_HEATING,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                            min=60,
                            max=7200,
                            step=60,
                            unit_of_measurement="s",
                        )
                    ),
                    vol.Optional(
                        CONF_MIN_RUN_AC,
                        default=DEFAULT_MIN_RUN_AC,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                            min=60,
                            max=7200,
                            step=60,
                            unit_of_measurement="s",
                        )
                    ),
                    vol.Optional(
                        CONF_MIN_IDLE,
                        default=DEFAULT_MIN_IDLE,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                            min=0,
                            max=7200,
                            step=60,
                            unit_of_measurement="s",
                        )
                    ),
                    vol.Optional(
                        CONF_AC_SETPOINT_OFFSET,
                        default=DEFAULT_AC_SETPOINT_OFFSET,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                            min=-2,
                            max=8,
                            step=0.1,
                            unit_of_measurement="°C",
                        )
                    ),
                    vol.Optional(CONF_COP_POINTS): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.TEXT,
                            multiline=True,
                        )
                    ),
                },
                extra=vol.REMOVE_EXTRA,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("HybridHeat: building globals schema failed")
            return self.async_abort(reason="unknown")

        return self.async_show_form(
            step_id="globals",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """TODO: Options flow for tuning without re-adding the room."""
        return HybridHeatOptionsFlow(config_entry)


def _normalize_entry(data: dict[str, Any]) -> dict[str, Any]:
    """Strip optional keys and normalize types for storage."""
    out: dict[str, Any] = dict(data)

    for price_key in (
        CONF_ELECTRICITY_PRICE_PER_KWH,
        CONF_GAS_PRICE_PER_KWH,
        CONF_FEED_IN_PRICE_PER_KWH,
    ):
        if price_key in out and out[price_key] is not None:
            out[price_key] = float(out[price_key])

    if out.get(CONF_ELECTRICITY_PRICE_PER_KWH) is not None:
        out.pop(CONF_ELECTRICITY_PRICE_SENSOR, None)
    if out.get(CONF_GAS_PRICE_PER_KWH) is not None:
        out.pop(CONF_GAS_PRICE_SENSOR, None)
    if out.get(CONF_FEED_IN_PRICE_PER_KWH) is not None:
        out.pop(CONF_FEED_IN_SENSOR, None)

    if CONF_AC_SETPOINT_OFFSET in out and out[CONF_AC_SETPOINT_OFFSET] is not None:
        out[CONF_AC_SETPOINT_OFFSET] = float(out[CONF_AC_SETPOINT_OFFSET])

    for key in (CONF_BATTERY_SOC_SENSOR, CONF_HOUSE_POWER_ENTITY):
        if out.get(key) in (None, "", "unknown"):
            out.pop(key, None)

    cap = float(out.get(CONF_BATTERY_CAPACITY_KWH) or 0)
    if cap <= 0:
        for k in (
            CONF_BATTERY_CAPACITY_KWH,
            CONF_BATTERY_MIN_SOC,
            CONF_BATTERY_MAX_SOC,
            CONF_BATTERY_SOC_SENSOR,
        ):
            out.pop(k, None)
    else:
        out[CONF_BATTERY_CAPACITY_KWH] = cap

    fs = out.get(CONF_FORECAST_SOLAR_ENTITIES)
    if isinstance(fs, str):
        out[CONF_FORECAST_SOLAR_ENTITIES] = [fs] if fs else []
    elif fs is None:
        out[CONF_FORECAST_SOLAR_ENTITIES] = []
    if not out[CONF_FORECAST_SOLAR_ENTITIES]:
        raise ValueError("At least one Forecast.Solar (or PV forecast) entity is required")

    if not out.get(CONF_HOUSE_POWER_ENTITY):
        out.pop(CONF_HOUSE_POWER_ENTITY, None)

    cop_txt = out.get(CONF_COP_POINTS)
    if isinstance(cop_txt, str) and not cop_txt.strip():
        out.pop(CONF_COP_POINTS, None)

    return out


class HybridHeatOptionsFlow(config_entries.OptionsFlow):  # type: ignore[misc]
    """Options flow for shared parameters across all HybridHeat rooms."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        super().__init__()
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Edit shared settings and apply them to all rooms."""
        current = self._current_values()
        if user_input is not None:
            try:
                normalized = _normalize_entry(dict(user_input))
                patch = {k: normalized[k] for k in SHARED_OPTION_KEYS if k in normalized}
                for entry in self.hass.config_entries.async_entries(DOMAIN):
                    data = dict(entry.data)
                    data.update(patch)
                    if entry.entry_id == self._entry.entry_id:
                        if CONF_AC_SETPOINT_OFFSET in normalized:
                            data[CONF_AC_SETPOINT_OFFSET] = normalized[
                                CONF_AC_SETPOINT_OFFSET
                            ]
                    self.hass.config_entries.async_update_entry(entry, data=data)
                    await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_create_entry(title="", data={})
            except ValueError:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self.add_suggested_values_to_schema(
                        self._build_schema(), current
                    ),
                    errors={"base": "forecast_required"},
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("HybridHeat: options update failed: %s", err, exc_info=True)
                return self.async_show_form(
                    step_id="init",
                    data_schema=self.add_suggested_values_to_schema(
                        self._build_schema(), current
                    ),
                    errors={"base": "unknown"},
                )

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(self._build_schema(), current),
            errors={},
        )

    def _current_values(self) -> dict[str, Any]:
        d = dict(self._entry.data)
        d.update(self._entry.options)
        return globals_form_values_from_merged_data(d)

    def _build_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_OUTDOOR_TEMP_SENSOR): _sensor_selector(),
                vol.Required(CONF_ELECTRICITY_PRICE_PER_KWH): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=0,
                        max=5,
                        step=0.001,
                        unit_of_measurement="€/kWh",
                    )
                ),
                vol.Required(CONF_GAS_PRICE_PER_KWH): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=0,
                        max=5,
                        step=0.001,
                        unit_of_measurement="€/kWh",
                    )
                ),
                vol.Required(CONF_FEED_IN_PRICE_PER_KWH): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=0,
                        max=5,
                        step=0.001,
                        unit_of_measurement="€/kWh",
                    )
                ),
                vol.Required(CONF_FORECAST_SOLAR_ENTITIES): _sensor_selector(multiple=True),
                vol.Optional(CONF_BATTERY_CAPACITY_KWH): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=0,
                        max=200,
                        step=0.1,
                        unit_of_measurement="kWh",
                    )
                ),
                vol.Optional(CONF_BATTERY_MIN_SOC): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=0,
                        max=100,
                        step=1,
                        unit_of_measurement="%",
                    )
                ),
                vol.Optional(CONF_BATTERY_MAX_SOC): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=0,
                        max=100,
                        step=1,
                        unit_of_measurement="%",
                    )
                ),
                vol.Optional(CONF_BASE_LOAD_W): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=0,
                        max=20000,
                        step=50,
                        unit_of_measurement="W",
                    )
                ),
                vol.Optional(CONF_HEATING_EFFICIENCY): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=0.5,
                        max=1.0,
                        step=0.01,
                    )
                ),
                vol.Optional(CONF_HYSTERESIS): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=0.1,
                        max=3.0,
                        step=0.05,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(CONF_MIN_RUN_HEATING): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=60,
                        max=7200,
                        step=60,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(CONF_MIN_RUN_AC): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=60,
                        max=7200,
                        step=60,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(CONF_MIN_IDLE): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=0,
                        max=7200,
                        step=60,
                        unit_of_measurement="s",
                    )
                ),
                vol.Optional(CONF_AC_SETPOINT_OFFSET): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=-2,
                        max=8,
                        step=0.1,
                        unit_of_measurement="°C",
                    )
                ),
                vol.Optional(CONF_COP_POINTS): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.TEXT,
                        multiline=True,
                    )
                ),
            },
            extra=vol.REMOVE_EXTRA,
        )
