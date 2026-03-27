"""Dataclasses and typed models for HybridHeat."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ActiveSource = Literal["heating", "ac", "none"]


@dataclass(frozen=True, slots=True)
class CopPoint:
    """Single COP support point: outdoor temperature (°C) -> COP."""

    outdoor_temp_c: float
    cop: float


@dataclass(slots=True)
class RoomConfig:
    """Per-room configuration from config entry."""

    room_name: str
    heating_climate_entity_id: str
    ac_climate_entity_id: str
    room_temp_sensor_entity_id: str
    heating_efficiency: float
    cop_points: tuple[CopPoint, ...]
    hysteresis_c: float
    min_run_heating_s: int
    min_run_ac_s: int
    min_idle_after_switch_s: int
    ac_setpoint_offset_c: float = 0.0


@dataclass(slots=True)
class GlobalSensorConfig:
    """Global sensors, static €/kWh prices (or legacy price sensors), optional battery / load."""

    outdoor_temp_sensor_entity_id: str
    forecast_solar_entity_ids: tuple[str, ...]
    electricity_price_per_kwh: float | None = None
    gas_price_per_kwh: float | None = None
    feed_in_price_per_kwh: float | None = None
    electricity_price_sensor_entity_id: str | None = None
    gas_price_sensor_entity_id: str | None = None
    feed_in_sensor_entity_id: str | None = None
    battery_soc_sensor_entity_id: str | None = None
    battery_capacity_kwh: float | None = None
    battery_min_soc_pct: float | None = None
    battery_max_soc_pct: float | None = None
    house_power_entity_id: str | None = None
    base_load_w: float | None = None


@dataclass(slots=True)
class SnapshotInputs:
    """Point-in-time readings used by the engine and coordinator."""

    room_temp_c: float | None = None
    target_temp_c: float | None = None
    outdoor_temp_c: float | None = None
    electricity_price: float | None = None
    gas_price: float | None = None
    feed_in_price: float | None = None
    forecast_pv_w: float | None = None
    house_load_w: float | None = None
    battery_soc_pct: float | None = None
    battery_capacity_kwh: float | None = None


@dataclass(slots=True)
class CostEvaluation:
    """Intermediate cost breakdown (per kWh useful heat, monetary units as per sensors)."""

    gas_price_per_kwh_fuel: float | None = None
    gas_heat_cost_per_kwh: float | None = None
    cop_at_outdoor: float | None = None
    effective_electricity_price: float | None = None
    ac_heat_cost_per_kwh: float | None = None
    pv_surplus_factor: float = 0.0  # 0..1 heuristic


@dataclass(slots=True)
class DecisionResult:
    """Outcome of the decision engine for one evaluation cycle."""

    desired_active_source: ActiveSource
    should_apply_heat: bool
    should_apply_cool: bool = False
    costs: CostEvaluation = field(default_factory=CostEvaluation)
    reason: str = ""
    # When True, prefer keeping current source even if the other is marginally cheaper (anti-flap).
    lock_source: bool = False
