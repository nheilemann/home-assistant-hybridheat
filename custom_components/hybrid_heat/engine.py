"""Heuristic decision engine: gas vs heat-pump (AC) economics with stability rules."""

from __future__ import annotations

import logging
import math
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING

from .const import SOURCE_AC, SOURCE_HEATING, SOURCE_NONE
from .models import (
    ActiveSource,
    CostEvaluation,
    DecisionResult,
    GlobalSensorConfig,
    RoomConfig,
    SnapshotInputs,
)

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)

def interpolate_cop(outdoor_temp_c: float, cop_support: list[tuple[float, float]]) -> float:
    """Linear interpolation of COP from (temp_c, cop) support points.

    Support points are sorted by temperature. Values outside the range are clamped
    to the nearest edge (constant extrapolation).
    """
    if not cop_support:
        return 3.0

    sorted_pts = sorted(cop_support, key=lambda p: p[0])
    if outdoor_temp_c <= sorted_pts[0][0]:
        return sorted_pts[0][1]
    if outdoor_temp_c >= sorted_pts[-1][0]:
        return sorted_pts[-1][1]

    for i in range(len(sorted_pts) - 1):
        t0, c0 = sorted_pts[i]
        t1, c1 = sorted_pts[i + 1]
        if t0 <= outdoor_temp_c <= t1:
            if t1 == t0:
                return c0
            w = (outdoor_temp_c - t0) / (t1 - t0)
            return c0 + w * (c1 - c0)

    return sorted_pts[-1][1]


def compute_pv_surplus_factor(
    inputs: SnapshotInputs,
    global_cfg: GlobalSensorConfig,
) -> tuple[float, bool]:
    """Heuristic 0..1: how much marginal electricity for AC behaves like 'PV / export opportunity'.

    Uses forecast PV power vs house load (entity or base load). Does NOT model room solar gain.
    Returns (factor, surplus_expected_bool).
    """
    forecast_w = inputs.forecast_pv_w
    load_w = inputs.house_load_w
    if global_cfg.base_load_w is not None and load_w is None:
        load_w = global_cfg.base_load_w

    if forecast_w is None or load_w is None:
        return 0.0, False

    try:
        margin = float(forecast_w) - float(load_w)
    except (TypeError, ValueError):
        return 0.0, False

    surplus_expected = margin > 0
    # Soft saturation: margin / scale capped to 1.0
    scale = max(abs(float(forecast_w)), 500.0)
    factor = max(0.0, min(1.0, margin / scale))
    return factor, surplus_expected


def compute_effective_electricity_price(
    grid_price: float,
    feed_in: float,
    pv_factor: float,
    battery_soc_pct: float | None,
    battery_min_soc: float | None,
    battery_max_soc: float | None,
) -> float:
    """Blend grid and opportunity cost of PV/export.

    When PV surplus is expected (high pv_factor), marginal kWh for the load often displaces
    export; opportunity cost is at least the feed-in tariff (not 'free solar').

    Optional battery: MVP only nudges effective price when SoC is outside comfortable band
    (battery is observed, not controlled).
    """
    feed_in = max(feed_in, 0.0)
    marginal_pv = feed_in  # simplified: foregone export per kWh used on-site
    raw = (1.0 - pv_factor) * grid_price + pv_factor * marginal_pv

    nudge = 0.0
    if battery_soc_pct is not None:
        if battery_min_soc is not None and battery_soc_pct < battery_min_soc:
            nudge += 0.005 * (battery_min_soc - battery_soc_pct)  # gently discourage electrical heating
        if battery_max_soc is not None and battery_soc_pct > battery_max_soc - 5.0:
            # Plenty of headroom in battery — slight favor to using electricity if already cheap
            nudge -= 0.005 * min(5.0, battery_soc_pct - (battery_max_soc - 5.0))

    return max(0.0, raw + nudge)


def evaluate_costs(
    inputs: SnapshotInputs,
    room: RoomConfig,
    global_cfg: GlobalSensorConfig,
) -> CostEvaluation | None:
    """Compute gas vs AC marginal heat costs. Returns None if required inputs missing."""
    if (
        inputs.electricity_price is None
        or inputs.gas_price is None
        or inputs.feed_in_price is None
        or inputs.outdoor_temp_c is None
    ):
        return None

    grid_price = inputs.electricity_price
    gas_fuel_price = inputs.gas_price
    feed_in = inputs.feed_in_price

    cop_support = [(p.outdoor_temp_c, p.cop) for p in room.cop_points]
    cop = interpolate_cop(inputs.outdoor_temp_c, cop_support)

    pv_factor, _ = compute_pv_surplus_factor(inputs, global_cfg)
    effective_el = compute_effective_electricity_price(
        grid_price,
        feed_in,
        pv_factor,
        inputs.battery_soc_pct,
        global_cfg.battery_min_soc_pct,
        global_cfg.battery_max_soc_pct,
    )

    eff = max(room.heating_efficiency, 0.01)
    gas_heat_cost = gas_fuel_price / eff
    ac_heat_cost = effective_el / max(cop, 0.1)

    return CostEvaluation(
        gas_price_per_kwh_fuel=gas_fuel_price,
        gas_heat_cost_per_kwh=gas_heat_cost,
        cop_at_outdoor=cop,
        effective_electricity_price=effective_el,
        ac_heat_cost_per_kwh=ac_heat_cost,
        pv_surplus_factor=pv_factor,
    )


def heating_demand_with_hysteresis(
    room_temp: float | None,
    target: float | None,
    hysteresis_c: float,
    currently_heating: bool,
) -> tuple[bool, str]:
    """Demand true if we should actively heat toward target (symmetric band)."""
    if room_temp is None or target is None:
        return False, "missing room or target temperature"

    half = max(hysteresis_c, 0.05) / 2.0
    if currently_heating:
        if room_temp < target - half:
            return True, f"room {room_temp:.2f}°C below heat-off threshold {target - half:.2f}°C"
        if room_temp > target + half:
            return False, f"room {room_temp:.2f}°C above heat-off threshold {target + half:.2f}°C"
        return True, f"within heating band (hysteresis), room {room_temp:.2f}°C"

    if room_temp < target - half:
        return True, f"room {room_temp:.2f}°C below heat-on threshold {target - half:.2f}°C"
    return False, f"room {room_temp:.2f}°C above heat-on threshold {target - half:.2f}°C"


def decide(
    inputs: SnapshotInputs,
    room: RoomConfig,
    global_cfg: GlobalSensorConfig,
    *,
    current_source: ActiveSource,
    now: datetime,
    last_source_change_at: datetime | None,
    source_run_started_at: datetime | None,
) -> DecisionResult:
    """Pick heating vs AC vs none with min run / idle and anti-flap."""

    _, pv_surplus_expected = compute_pv_surplus_factor(inputs, global_cfg)

    costs = evaluate_costs(inputs, room, global_cfg)
    if costs is None:
        return DecisionResult(
            desired_active_source=SOURCE_NONE,
            should_apply_heat=False,
            costs=CostEvaluation(pv_surplus_factor=compute_pv_surplus_factor(inputs, global_cfg)[0]),
            reason="preise oder außentemperatur nicht verfügbar — keine Heizentscheidung",
            lock_source=True,
        )

    room_temp = inputs.room_temp_c
    target = inputs.target_temp_c
    # "Currently heating" for hysteresis: room actively being heated if source is not none
    heating_now = current_source != SOURCE_NONE
    need_heat, heat_reason = heating_demand_with_hysteresis(
        room_temp, target, room.hysteresis_c, heating_now
    )

    if not need_heat:
        return DecisionResult(
            desired_active_source=SOURCE_NONE,
            should_apply_heat=False,
            costs=costs,
            reason=f"kein Heizbedarf ({heat_reason}); PV-Überschuss erwartet: {pv_surplus_expected}",
        )

    g_cost = costs.gas_heat_cost_per_kwh
    a_cost = costs.ac_heat_cost_per_kwh
    if g_cost is None or a_cost is None:
        return DecisionResult(
            desired_active_source=SOURCE_NONE,
            should_apply_heat=True,
            costs=costs,
            reason="kosten nicht berechenbar",
            lock_source=True,
        )

    cheaper: ActiveSource
    if math.isclose(g_cost, a_cost, rel_tol=0.04, abs_tol=1e-4):
        cheaper = (
            current_source
            if current_source in (SOURCE_HEATING, SOURCE_AC)
            else (SOURCE_HEATING if g_cost <= a_cost else SOURCE_AC)
        )
        econ_reason = (
            f"kosten nahezu gleich (Gas {g_cost:.4f} ≈ AC {a_cost:.4f}); gewählt: {cheaper}"
        )
    elif g_cost < a_cost:
        cheaper = SOURCE_HEATING
        econ_reason = f"günstiger: Heizung (Gas-Wärme {g_cost:.4f} < AC-Wärme {a_cost:.4f})"
    else:
        cheaper = SOURCE_AC
        econ_reason = f"günstiger: Klima (AC-Wärme {a_cost:.4f} < Gas-Wärme {g_cost:.4f})"

    desired = cheaper
    reason = f"{heat_reason}. {econ_reason}. COP≈{costs.cop_at_outdoor:.2f}, eff. Strom {costs.effective_electricity_price:.4f}"

    lock_source = False

    # Min run time for current source
    if current_source == SOURCE_HEATING and source_run_started_at is not None:
        ran = (now - source_run_started_at).total_seconds()
        if ran < room.min_run_heating_s and desired != SOURCE_HEATING:
            desired = SOURCE_HEATING
            lock_source = True
            reason += f"; mindestlaufzeit Heizung ({ran:.0f}s < {room.min_run_heating_s}s)"
    if current_source == SOURCE_AC and source_run_started_at is not None:
        ran = (now - source_run_started_at).total_seconds()
        if ran < room.min_run_ac_s and desired != SOURCE_AC:
            desired = SOURCE_AC
            lock_source = True
            reason += f"; mindestlaufzeit Klima ({ran:.0f}s < {room.min_run_ac_s}s)"

    # Idle time after last switch before allowing opposite source
    if last_source_change_at is not None:
        idle = (now - last_source_change_at).total_seconds()
        if idle < room.min_idle_after_switch_s:
            if current_source in (SOURCE_HEATING, SOURCE_AC) and desired != current_source:
                desired = current_source
                lock_source = True
                reason += (
                    f"; stillstand nach umschalten ({idle:.0f}s < {room.min_idle_after_switch_s}s)"
                )

    return DecisionResult(
        desired_active_source=desired,
        should_apply_heat=True,
        costs=replace(costs),
        reason=reason,
        lock_source=lock_source,
    )
