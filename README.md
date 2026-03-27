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

1. **Config flow** (UI): room name, required entities, fixed €/kWh prices, shared-style global sensors (outdoor, PV forecast), optional battery / load / COP text.
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

Create **one config entry per room**. Shared settings can be edited from any room entry via the gear icon (options) and are applied to all HybridHeat rooms.

### Troubleshooting & logs

Config-flow validation errors often return **HTTP 400** in the browser **before** Python runs, so you may see nothing under `custom_components.hybrid_heat` until the flow reaches our code.

- In the browser **Network** tab, open the failing `flow/{flow_id}` request: a valid HA response is usually **JSON** `{"errors": { ... }}` (field-level hints). If you only see **plain text** and very few bytes, a **proxy (e.g. Cloudflare)** or the client may be altering the response—try from the local HA URL or check the full log on the server.

- Config flow `data_schema` values must be serializable for the UI (selectors, standard `vol` validators). **Custom Python functions inside `vol.All` break** `voluptuous_serialize` and produce **500** (“Unable to convert schema”). **`vol.Any` (including `vol.Any(vol.In(...), EntitySelector)`) is also not serializable** in current HA / `voluptuous_serialize` — avoid it in `data_schema`; use plain `vol.Optional` + a single `EntitySelector` / `TextSelector` only.

- **Translations:** The UI reads labels from `custom_components/hybrid_heat/translations/{lang}.json` (e.g. `en.json`, `de.json`). `strings.json` alone is often not enough. After updating files, do a **full Home Assistant restart** (not only “reload integration”). If labels stay raw, hard-refresh the browser or clear the frontend cache.

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

- Outdoor temperature (`sensor.*`, `weather.*`, or another entity with a numeric state or a `temperature` / `current_temperature` attribute — plain `weather` states like `sunny` are not numeric)  
- Fixed **grid, gas, and feed-in prices** (€/kWh in the config UI)  
- One or more sensors for **expected PV power** (e.g. Forecast.Solar “power now / next hour”, depending on your setup)

**Optional**  

- Battery **capacity** (kWh) and SoC **limits** for heuristics (no SoC sensor in the config UI yet — options flow `TODO`; set capacity to `0` to disable battery)  
- **Base load** (W) for forecast vs consumption (house power entity picker removed from the flow for the same serialization constraint)  
- COP points as text: `-5:2.2, 0:2.8, 5:3.4, 10:4.0`  
- Heating efficiency η, hysteresis, min run / idle times  

Keep **price units consistent** (e.g. all €/kWh). New setups use **numeric price fields** in the config flow; older entries that still reference **price sensors** keep working until you reconfigure.

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
- One entry per room (shared settings are synced across all room entries via options flow).  

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
