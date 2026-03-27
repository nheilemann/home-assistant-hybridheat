"""HybridHeat: cost-aware hybrid room heating for Home Assistant."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

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
    DEFAULT_COP_POINTS,
    DEFAULT_HEATING_EFFICIENCY,
    DEFAULT_HYSTERESIS,
    DEFAULT_MIN_IDLE,
    DEFAULT_MIN_RUN_AC,
    DEFAULT_AC_SETPOINT_OFFSET,
    DEFAULT_MIN_RUN_HEATING,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import HybridHeatCoordinator
from .models import CopPoint, GlobalSensorConfig, RoomConfig

_LOGGER = logging.getLogger(__name__)


def parse_cop_points(raw: Any) -> tuple[CopPoint, ...]:
    """Parse COP support points from config (string, list, or None)."""
    default = tuple(CopPoint(t, c) for t, c in DEFAULT_COP_POINTS)

    if raw is None:
        return default

    if isinstance(raw, list):
        pts: list[CopPoint] = []
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                pts.append(CopPoint(float(item[0]), float(item[1])))
            elif isinstance(item, dict):
                t = item.get("t", item.get("outdoor_temp_c"))
                c = item.get("cop")
                if t is not None and c is not None:
                    pts.append(CopPoint(float(t), float(c)))
        if len(pts) >= 2:
            return tuple(sorted(pts, key=lambda p: p.outdoor_temp_c))
        return default

    if isinstance(raw, str) and raw.strip():
        pts: list[CopPoint] = []
        for part in raw.replace("\n", ",").split(","):
            part = part.strip()
            if ":" not in part:
                continue
            a, b = part.split(":", 1)
            pts.append(CopPoint(float(a.strip()), float(b.strip())))
        if len(pts) >= 2:
            return tuple(sorted(pts, key=lambda p: p.outdoor_temp_c))

    return default


def build_room_config(entry: ConfigEntry) -> RoomConfig:
    """Hydrate `RoomConfig` from a config entry."""
    d = dict(entry.data)
    d.update(entry.options)
    return RoomConfig(
        room_name=d[CONF_ROOM_NAME],
        heating_climate_entity_id=d[CONF_HEATING_CLIMATE],
        ac_climate_entity_id=d[CONF_AC_CLIMATE],
        room_temp_sensor_entity_id=d[CONF_ROOM_TEMP_SENSOR],
        heating_efficiency=float(d.get(CONF_HEATING_EFFICIENCY, DEFAULT_HEATING_EFFICIENCY)),
        cop_points=parse_cop_points(d.get(CONF_COP_POINTS)),
        hysteresis_c=float(d.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS)),
        min_run_heating_s=int(d.get(CONF_MIN_RUN_HEATING, DEFAULT_MIN_RUN_HEATING)),
        min_run_ac_s=int(d.get(CONF_MIN_RUN_AC, DEFAULT_MIN_RUN_AC)),
        min_idle_after_switch_s=int(d.get(CONF_MIN_IDLE, DEFAULT_MIN_IDLE)),
        ac_setpoint_offset_c=float(
            d.get(CONF_AC_SETPOINT_OFFSET, DEFAULT_AC_SETPOINT_OFFSET)
        ),
    )


def build_global_config(entry: ConfigEntry) -> GlobalSensorConfig:
    """Hydrate global sensor references from a config entry."""
    d = dict(entry.data)
    d.update(entry.options)
    fs = d.get(CONF_FORECAST_SOLAR_ENTITIES) or []
    if isinstance(fs, str):
        fs = [fs]

    cap_raw = d.get(CONF_BATTERY_CAPACITY_KWH)
    has_battery = cap_raw is not None and float(cap_raw) > 0
    base = d.get(CONF_BASE_LOAD_W)

    el_p = d.get(CONF_ELECTRICITY_PRICE_PER_KWH)
    gas_p = d.get(CONF_GAS_PRICE_PER_KWH)
    fi_p = d.get(CONF_FEED_IN_PRICE_PER_KWH)

    return GlobalSensorConfig(
        outdoor_temp_sensor_entity_id=d[CONF_OUTDOOR_TEMP_SENSOR],
        forecast_solar_entity_ids=tuple(str(x) for x in fs),
        electricity_price_per_kwh=float(el_p)
        if el_p is not None
        else None,
        gas_price_per_kwh=float(gas_p) if gas_p is not None else None,
        feed_in_price_per_kwh=float(fi_p) if fi_p is not None else None,
        electricity_price_sensor_entity_id=d.get(CONF_ELECTRICITY_PRICE_SENSOR)
        if el_p is None
        else None,
        gas_price_sensor_entity_id=d.get(CONF_GAS_PRICE_SENSOR)
        if gas_p is None
        else None,
        feed_in_sensor_entity_id=d.get(CONF_FEED_IN_SENSOR) if fi_p is None else None,
        battery_soc_sensor_entity_id=d.get(CONF_BATTERY_SOC_SENSOR) if has_battery else None,
        battery_capacity_kwh=float(cap_raw) if has_battery else None,
        battery_min_soc_pct=float(d.get(CONF_BATTERY_MIN_SOC, 15.0)) if has_battery else None,
        battery_max_soc_pct=float(d.get(CONF_BATTERY_MAX_SOC, 95.0)) if has_battery else None,
        house_power_entity_id=d.get(CONF_HOUSE_POWER_ENTITY),
        base_load_w=float(base) if base is not None else None,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HybridHeat from a config entry."""
    _LOGGER.info(
        "HybridHeat: setting up config entry for room %s",
        entry.data.get(CONF_ROOM_NAME, entry.entry_id),
    )
    room_cfg = build_room_config(entry)
    global_cfg = build_global_config(entry)
    coordinator = HybridHeatCoordinator(hass, entry, room_cfg, global_cfg)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

    return unload_ok


async def async_setup(hass: HomeAssistant, _config: dict[str, Any]) -> bool:
    """YAML setup not used — integration is config-entry only (MVP)."""
    return True
