"""Constants for the HybridHeat integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "hybrid_heat"

# Config entry / flow keys
CONF_ROOM_NAME: Final = "room_name"
CONF_HEATING_CLIMATE: Final = "heating_climate_entity_id"
CONF_AC_CLIMATE: Final = "ac_climate_entity_id"
CONF_ROOM_TEMP_SENSOR: Final = "room_temp_sensor_entity_id"
CONF_OUTDOOR_TEMP_SENSOR: Final = "outdoor_temp_sensor_entity_id"
CONF_ELECTRICITY_PRICE_PER_KWH: Final = "electricity_price_per_kwh"
CONF_GAS_PRICE_PER_KWH: Final = "gas_price_per_kwh"
CONF_FEED_IN_PRICE_PER_KWH: Final = "feed_in_price_per_kwh"
# Legacy config entries (sensor entity IDs — still supported in coordinator)
CONF_ELECTRICITY_PRICE_SENSOR: Final = "electricity_price_sensor_entity_id"
CONF_GAS_PRICE_SENSOR: Final = "gas_price_sensor_entity_id"
CONF_FEED_IN_SENSOR: Final = "feed_in_sensor_entity_id"
CONF_FORECAST_SOLAR_ENTITIES: Final = "forecast_solar_entity_ids"
CONF_BATTERY_SOC_SENSOR: Final = "battery_soc_sensor_entity_id"
CONF_BATTERY_CAPACITY_KWH: Final = "battery_capacity_kwh"
CONF_BATTERY_MIN_SOC: Final = "battery_min_soc_pct"
CONF_BATTERY_MAX_SOC: Final = "battery_max_soc_pct"
CONF_HOUSE_POWER_ENTITY: Final = "house_power_entity_id"
CONF_BASE_LOAD_W: Final = "base_load_w"
CONF_HEATING_EFFICIENCY: Final = "heating_efficiency"
CONF_COP_POINTS: Final = "cop_points"
CONF_HYSTERESIS: Final = "hysteresis"
CONF_MIN_RUN_HEATING: Final = "min_run_heating_seconds"
CONF_MIN_RUN_AC: Final = "min_run_ac_seconds"
CONF_MIN_IDLE: Final = "min_idle_after_switch_seconds"

# Defaults
DEFAULT_HEATING_EFFICIENCY: Final = 0.92
DEFAULT_HYSTERESIS: Final = 0.5  # °C total band around target (split ± for heat on/off)
DEFAULT_MIN_RUN_HEATING: Final = 600  # 10 min
DEFAULT_MIN_RUN_AC: Final = 600
DEFAULT_MIN_IDLE: Final = 300  # 5 min after source change before reconsidering opposite source
DEFAULT_UPDATE_INTERVAL: Final = 60  # seconds
DEFAULT_ELECTRICITY_PRICE_PER_KWH: Final = 0.35
DEFAULT_GAS_PRICE_PER_KWH: Final = 0.12
DEFAULT_FEED_IN_PRICE_PER_KWH: Final = 0.08

# COP support points: outdoor_temp_c -> COP (linear interpolation between)
DEFAULT_COP_POINTS: Final[tuple[tuple[float, float], ...]] = (
    (-5.0, 2.2),
    (0.0, 2.8),
    (5.0, 3.4),
    (10.0, 4.0),
)

# Custom attributes on climate entity
ATTR_ACTIVE_SOURCE: Final = "active_source"
ATTR_EST_GAS_COST: Final = "estimated_gas_cost_per_kwh_heat"
ATTR_EST_AC_COST: Final = "estimated_ac_cost_per_kwh_heat"
ATTR_EFFECTIVE_ELECTRICITY: Final = "effective_electricity_price"
ATTR_PV_SURPLUS_EXPECTED: Final = "pv_surplus_expected"
ATTR_BATTERY_SOC: Final = "battery_soc"
ATTR_DECISION_REASON: Final = "decision_reason"

# Platform names
PLATFORMS: Final[list[str]] = ["climate", "sensor"]

# Sources (string values for attributes and engine)
SOURCE_HEATING: Final = "heating"
SOURCE_AC: Final = "ac"
SOURCE_NONE: Final = "none"
