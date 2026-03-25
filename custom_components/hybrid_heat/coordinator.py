"""DataUpdateCoordinator: collects sensor states for the hybrid engine."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN
from .models import DecisionResult, GlobalSensorConfig, RoomConfig, SnapshotInputs

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry


_LOGGER = logging.getLogger(__name__)


def _float_state(state: State | None) -> float | None:
    if state is None or state.state in ("unknown", "unavailable", None):
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


def _temperature_c(state: State | None) -> float | None:
    """°C from numeric state or common attributes (weather, climate, sensors)."""
    if state is None:
        return None
    v = _float_state(state)
    if v is not None:
        return v
    for key in (
        "temperature",
        "current_temperature",
        "native_temperature",
        "native_value",
    ):
        raw = state.attributes.get(key)
        if raw is None or raw in ("unknown", "unavailable"):
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _try_power_w(state: State | None) -> float | None:
    """Parse power in W from state or common attributes."""
    if state is None:
        return None
    v = _float_state(state)
    if v is not None:
        # Some sensors report kW
        u = state.attributes.get("unit_of_measurement", "")
        if isinstance(u, str) and "kw" in u.lower() and "kwh" not in u.lower():
            return v * 1000.0
        return v
    for key in ("power", "watts", "Power", "W"):
        if key in state.attributes:
            try:
                return float(state.attributes[key])
            except (TypeError, ValueError):
                continue
    return None


class HybridHeatCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches snapshot inputs for one config entry (one room)."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        room_config: RoomConfig,
        global_config: GlobalSensorConfig,
    ) -> None:
        self.entry = entry
        self.room_config = room_config
        self.global_config = global_config
        self.last_decision: DecisionResult | None = None
        self.last_pv_surplus_expected: bool = False

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=DEFAULT_UPDATE_INTERVAL),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Read all referenced entities into a snapshot."""
        try:
            snapshot = self._build_snapshot()
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"HybridHeat update failed: {err}") from err

        return {
            "snapshot": snapshot,
        }

    def _build_snapshot(self) -> SnapshotInputs:
        hass = self.hass
        gc = self.global_config
        rc = self.room_config

        room_s = hass.states.get(rc.room_temp_sensor_entity_id)
        outdoor_s = hass.states.get(gc.outdoor_temp_sensor_entity_id)

        if gc.electricity_price_per_kwh is not None:
            el_price: float | None = float(gc.electricity_price_per_kwh)
        else:
            el_price = _float_state(
                hass.states.get(gc.electricity_price_sensor_entity_id or "")
            )

        if gc.gas_price_per_kwh is not None:
            gas_price: float | None = float(gc.gas_price_per_kwh)
        else:
            gas_price = _float_state(
                hass.states.get(gc.gas_price_sensor_entity_id or "")
            )

        if gc.feed_in_price_per_kwh is not None:
            fi_price: float | None = float(gc.feed_in_price_per_kwh)
        else:
            fi_price = _float_state(hass.states.get(gc.feed_in_sensor_entity_id or ""))

        snap = SnapshotInputs(
            room_temp_c=_temperature_c(room_s),
            outdoor_temp_c=_temperature_c(outdoor_s),
            electricity_price=el_price,
            gas_price=gas_price,
            feed_in_price=fi_price,
        )

        if gc.battery_soc_sensor_entity_id:
            bs = hass.states.get(gc.battery_soc_sensor_entity_id)
            snap.battery_soc_pct = _float_state(bs)

        if gc.battery_capacity_kwh is not None:
            snap.battery_capacity_kwh = gc.battery_capacity_kwh

        # Forecast: sum available numeric estimates (W)
        forecast_total = 0.0
        count = 0
        for eid in gc.forecast_solar_entity_ids:
            st = hass.states.get(eid)
            w = _try_power_w(st)
            if w is not None:
                forecast_total += w
                count += 1
        if count > 0:
            snap.forecast_pv_w = forecast_total

        if gc.house_power_entity_id:
            hp = hass.states.get(gc.house_power_entity_id)
            snap.house_load_w = _try_power_w(hp)
        elif gc.base_load_w is not None:
            snap.house_load_w = float(gc.base_load_w)

        return snap
