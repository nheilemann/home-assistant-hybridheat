"""Config flow for HybridHeat (UI-based setup)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AC_CLIMATE,
    CONF_BASE_LOAD_W,
    CONF_BATTERY_CAPACITY_KWH,
    CONF_BATTERY_MAX_SOC,
    CONF_BATTERY_MIN_SOC,
    CONF_BATTERY_SOC_SENSOR,
    CONF_COP_POINTS,
    CONF_ELECTRICITY_PRICE_SENSOR,
    CONF_FEED_IN_SENSOR,
    CONF_FORECAST_SOLAR_ENTITIES,
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
    DEFAULT_HEATING_EFFICIENCY,
    DEFAULT_HYSTERESIS,
    DEFAULT_MIN_IDLE,
    DEFAULT_MIN_RUN_AC,
    DEFAULT_MIN_RUN_HEATING,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _climate_selector(multiple: bool = False) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="climate", multiple=multiple)
    )


def _sensor_selector(multiple: bool = False) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor", multiple=multiple)
    )


class HybridHeatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[misc]
    """Handle a config flow for HybridHeat (one config entry = one room)."""

    VERSION = 1

    def __init__(self) -> None:
        self._room_data: dict[str, Any] = {}

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
            schema = vol.Schema(
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
        except Exception:  # noqa: BLE001
            _LOGGER.exception("HybridHeat: building user-step schema failed")
            return self.async_abort(reason="unknown")

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_globals(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: global sensors, economics, stability, optional battery/load/COP text."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                data = {**self._room_data, **user_input}
                try:
                    normalized = _normalize_entry(data)
                except ValueError:
                    errors["base"] = "forecast_required"
                else:
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

        try:
            schema = vol.Schema(
                {
                    vol.Required(CONF_OUTDOOR_TEMP_SENSOR): _sensor_selector(),
                    vol.Required(CONF_ELECTRICITY_PRICE_SENSOR): _sensor_selector(),
                    vol.Required(CONF_GAS_PRICE_SENSOR): _sensor_selector(),
                    vol.Required(CONF_FEED_IN_SENSOR): _sensor_selector(),
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
            data_schema=schema,
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
    """Placeholder options flow — extend in a follow-up for shared global defaults."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        super().__init__()
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """TODO: expose hysteresis / min run / COP override without removing the entry."""
        return self.async_abort(reason="options_not_implemented")
