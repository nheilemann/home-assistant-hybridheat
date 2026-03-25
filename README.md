# HybridHeat – Home Assistant custom integration

**Hybrid room heating with cost-aware source selection.** HybridHeat exposes one **virtual `climate` entity per room**. You only set **target temperature** and **mode** (`off` / `heat`). The integration chooses between a **heating `climate`** (e.g. floor / gas) and an **AC `climate`** (split in heat mode) and drives both real devices conservatively in the background.

| | |
|---|---|
| **Integration domain** | `hybrid_heat` |
| **Type** | Native **custom integration** (not an add-on) |
| **Repository** | [github.com/nheilemann/home-assistant-hybridheat](https://github.com/nheilemann/home-assistant-hybridheat) |

## License

This project is released under the **[MIT License](LICENSE)**. It is a permissive license: you may use, modify, and distribute the code with few obligations; the software is provided **as-is** without warranty. This is a common choice for Home Assistant custom components.

## Scope and goals

- One **virtual room thermostat** that behaves like a normal heat thermostat.
- Each **polling cycle**, choose which physical heat source is active based on **marginal heat cost per kWh**, using:
  - gas price, grid electricity price, feed-in tariff  
  - **Forecast.Solar** / PV forecast (as an **economic / surplus signal**, not as solar gain into the room model)  
  - optional **battery** (SoC, capacity, limits – **observe only** in the MVP, no battery control)  
  - **COP curve** for the heat pump / AC vs outdoor temperature (support points + linear interpolation)
- **Stability:** hysteresis, minimum run times per source, minimum idle after switching, tie band to reduce flapping.

## MVP feature set

1. **Config flow** (UI): room name, required entities, global sensors, optional battery / load / COP text.
2. **Virtual `climate`** with `current_temperature`, `target_temperature`, `hvac_mode`, `hvac_action` and documented **custom attributes** (active source, cost estimates, effective power price, PV surplus hint, battery SoC if configured, decision text).
3. **Diagnostic sensors** (optional in the UI) for source, costs, COP, PV factor, reason.
4. **Heuristic engine** (no multi-hour optimisation): compares `gas_price / η` with `effective_electricity_price / COP`.

## Architecture

| Module | Role |
|--------|------|
| `__init__.py` | Lifecycle, build `RoomConfig` / `GlobalSensorConfig`, coordinator in `hass.data`. |
| `config_flow.py` | UI setup (one entry = one room). Options flow: placeholder (`TODO`). |
| `coordinator.py` | `DataUpdateCoordinator`: snapshot of temperatures, prices, forecast, load, battery. |
| `models.py` | Dataclasses: config, readings, costs, decision. |
| `engine.py` | COP interpolation, effective electricity price, cost comparison, hysteresis, timing rules. |
| `climate.py` | Virtual `ClimateEntity`, applies decisions via `climate.*` services defensively. |
| `sensor.py` | Diagnostic sensors from `coordinator.last_decision`. |

Forecast sensors are **not** modeled as direct heat input to the room; they inform whether **PV surplus** is likely and whether marginal kWh is closer to **grid price** or **opportunity cost of export** (feed-in).

**House load:** either optional **`house_power_entity`** or **`base_load_w`** for comparing forecast vs consumption.

## Installation

### Via HACS (recommended)

HybridHeat is **not** in the default HACS store. Add the repo as a **custom repository**:

1. Install and open [HACS](https://www.hacs.xyz/) in Home Assistant.
2. HACS → **Integrations** → **⋮** → **Custom repositories**.
3. URL: `https://github.com/nheilemann/home-assistant-hybridheat` — category **Integration** → **Add**.
4. Find **HybridHeat** under **Integrations** → **Download** (pick branch/version as usual).
5. **Restart** Home Assistant.
6. **Settings → Devices & services → Add integration** → set up **HybridHeat**.

### Manual (custom component)

1. Copy `custom_components/hybrid_heat` from this repo to `<config>/custom_components/hybrid_heat/`.
2. Restart Home Assistant.
3. **Settings → Devices & services → Add integration** → **HybridHeat**.

### After installation

Create **one config entry per room** (you may reuse the same global sensor entities across entries; a single shared global setup step is still `TODO`).

### Troubleshooting & logs

Config-flow validation errors often return **HTTP 400** in the browser **before** Python runs, so you may see nothing under `custom_components.hybrid_heat` until the flow reaches our code.

- **Settings → System → Logs** (or **full log** download). Filter or search for `hybrid_heat`.
- To force more detail, add to `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.hybrid_heat: debug
```

After a successful setup you should see a line like `HybridHeat: setting up config entry for room …` at **info** level.

## Configuration

**Per room (required)**  

- Heating `climate`  
- AC `climate` (heat mode)  
- Room temperature `sensor`

**Global (per entry — usually pick the same entities each time)**  

- Outdoor temperature  
- Electricity, gas, feed-in sensors  
- One or more sensors for **expected PV power** (e.g. Forecast.Solar “power now / next hour”, depending on your setup)

**Optional**  

- Battery SoC, usable capacity (kWh), SoC limits for heuristics  
- House power or base load (W)  
- COP points as text: `-5:2.2, 0:2.8, 5:3.4, 10:4.0`  
- Heating efficiency η, hysteresis, min run / idle times  

Keep **price units consistent** (e.g. all €/kWh); the integration only reads **numeric** states.

## Cost logic (short)

- **Gas heat (per kWh useful heat):** `gas_heat_cost = gas_price / heating_efficiency`
- **AC heat:** `ac_heat_cost = effective_electricity_price / COP(T_outdoor)`
- **Effective electricity:** blend of grid and feed-in tariff weighted by a **PV surplus factor** (0…1) from forecast minus load. PV is **not** treated as “free”; export opportunity cost is at least the feed-in value.

## Virtual climate behaviour

- MVP modes: **`off`**, **`heat`** (structure can later add **`auto`**, `TODO`).
- Extra attributes include: `active_source` (`heating` / `ac` / `none`), cost estimates, `effective_electricity_price`, `pv_surplus_expected`, `battery_soc`, `decision_reason`.

Child devices are only called when mode or setpoint **actually needs** to change.

## Known MVP limitations

- No MPC, no learned thermal model.  
- **Cooling** not in scope.  
- **Battery** is not charged/discharged by this integration.  
- **Forecast** parsing is simple — use a **template sensor** in front of unusual entities.  
- One entry per room: **shared** global config without duplication is `TODO`.  
- **Options flow** for post-setup edits is not implemented yet.

## Roadmap / TODOs

- Shared **global config** (prices / forecast / battery once, many rooms).  
- Full **options flow** (hysteresis, COP, swap entities).  
- **`auto`** mode / comfort extras.  
- Richer **forecast / time series** handling.  
- Unit tests for `engine` without Home Assistant.

## Quality

- Runs **locally**; no cloud dependency.  
- Clear split: **models → engine → platform code**.  
- Typed Python, readable comments, explicit **TODO** markers for extensions.
