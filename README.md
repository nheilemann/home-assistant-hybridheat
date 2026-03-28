# HybridHeat – Home Assistant custom integration

**Hybrid room heating (and optional cooling) with cost-aware source selection.** HybridHeat exposes one **virtual `climate` entity per room**. You set **target temperature** and **mode** (`off` / `heat` / `cool`). In **heat**, the integration chooses between a **heating `climate`** (e.g. floor / gas) and an **AC `climate`**; in **cool**, only the **AC** runs (primary heating is off). Both real devices are driven conservatively in the background.

| | |
|---|---|
| **Integration domain** | `hybrid_heat` |
| **Type** | Native **custom integration** (not an add-on) |
| **Repository** | [github.com/nheilemann/home-assistant-hybridheat](https://github.com/nheilemann/home-assistant-hybridheat) |

## License

This project is released under the **[MIT License](LICENSE)**. It is a permissive license: you may use, modify, and distribute the code with few obligations; the software is provided **as-is** without warranty. This is a common choice for Home Assistant custom components.

## Scope and goals

- One **virtual room thermostat** with **heat** and **cool** modes (primary heating is not used for cooling).
- Each **polling cycle**, choose which physical heat source is active based on **marginal heat cost per kWh**, using:
  - gas price, grid electricity price, feed-in tariff  
  - **Forecast.Solar** / PV forecast (as an **economic / surplus signal**, not as solar gain into the room model)  
  - optional **battery** (SoC, capacity, limits – **observe only** in the MVP, no battery control)  
  - **COP curve** for the heat pump / AC vs outdoor temperature (support points + linear interpolation)
- **Stability:** hysteresis, minimum run times per source, minimum idle after switching, tie band to reduce flapping.

## MVP feature set

1. **Config flow** (UI): room name, required entities, fixed €/kWh prices, global sensors (outdoor, PV forecast), optional battery / load / COP text. **Additional rooms:** the globals step is **pre-filled** from the most recently added HybridHeat entry (AC setpoint offset stays per room). If the AC entity’s state lists `hvac_modes` **without** `cool`, a **menu** offers another AC entity or heat-only continue.
2. **Virtual `climate`** with `current_temperature`, `target_temperature`, `hvac_mode`, `hvac_action` and **state attributes**: decision/cost diagnostics plus **`hh_*` room settings** (linked climates, sensor IDs, offset, η, hysteresis, min run/idle, COP text) and **`hh_temperature_inputs`** (room vs outdoor sensor: entity, friendly name, current °C, short note on what each measures). **`cool`** appears in the UI only if the configured AC lists `cool` in `hvac_modes`. **`hvac_mode` and target** are **restored after a Home Assistant restart** via Home Assistant’s **restore state** (Recorder / `core.restore_state`); without that, startup defaults apply.
3. **Diagnostic sensors** (optional in the UI) for source, costs, COP, PV factor, reason.
4. **Heuristic engine** (no multi-hour optimisation): compares `gas_price / η` with `effective_electricity_price / COP` for heating; **cool** uses the AC only with the same effective electricity and **COP** curve as a rough cooling-efficiency hint (SEER-accurate points are not required in the MVP).

## Architecture

| Module | Role |
|--------|------|
| `__init__.py` | Lifecycle, build `RoomConfig` / `GlobalSensorConfig`, coordinator in `hass.data`. |
| `config_flow.py` | UI setup (one entry = one room); **options flow** updates shared fields for **all** HybridHeat entries. |
| `coordinator.py` | `DataUpdateCoordinator`: snapshot of temperatures, prices, forecast, load, battery. |
| `models.py` | Dataclasses: config, readings, costs, decision. |
| `engine.py` | COP interpolation, effective electricity price, cost comparison, hysteresis, timing rules. |
| `climate.py` | Virtual `ClimateEntity` + `RestoreEntity`; applies decisions via `climate.*` only when the **desired hybrid state** (mode, target, engine output) **changes**, to avoid redundant device commands. |
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

Create **one config entry per room**. Shared settings can be edited from any room entry via the gear icon (**options**) and are **written to every** HybridHeat config entry and reloaded. When adding a **second or later** room, the globals step suggests values from the latest existing entry.

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
- AC `climate` (heat & cool, if the device exposes `cool`)  
- Room temperature `sensor`

**Global (per entry — usually pick the same entities each time)**  

- Outdoor temperature (`sensor.*`, `weather.*`, or another entity with a numeric state or a `temperature` / `current_temperature` attribute — plain `weather` states like `sunny` are not numeric)  
- Fixed **grid, primary-energy, and feed-in prices** (€/kWh in the config UI)  
- One or more sensors for **expected PV power** (e.g. Forecast.Solar “power now / next hour”, depending on your setup)

**Optional**  

- Battery **capacity** (kWh) and SoC **limits** for heuristics (set capacity to `0` to disable battery). **Battery SoC sensor** and **house power** entity are not in the setup form; they can be merged from another room on first install or set in the entry (e.g. YAML / repair) if needed.  
- **Base load** (W) for forecast vs consumption (house power entity picker removed from the flow for the same serialization constraint)  
- COP points as text: `-5:2.2, 0:2.8, 5:3.4, 10:4.0`  
- **AC setpoint offset (°C):** added only to the commanded temperature of the AC `climate` when HybridHeat selects it, so the unit keeps heating if its **built-in sensor** reaches setpoint before your **room thermostat sensor** (e.g. room 19 °C, AC thinks 21 °C → try offset **+2**). Clamped to the virtual thermostat min/max.  
- Heating efficiency η, hysteresis, min run / idle times  

Keep **price units consistent** (e.g. all €/kWh). New setups use **numeric price fields** in the config flow; older entries that still reference **price sensors** keep working until you reconfigure.

### COP points from EU energy label

`cop_points` expects operating points in the form:

- `outdoor_temp_c:cop`
- Example: `-7:2.8, 0:3.6, 7:4.6, 12:5.0`

How to read the label:

- **SEER** (left side) is cooling season efficiency -> not used for heating decision.
- **SCOP** (right side) is heating season efficiency -> this is the useful anchor for `cop_points`.
- Many labels show SCOP per climate zone:
  - `warmer` (often highest SCOP),
  - `average` (usually central Europe reference),
  - `colder` (if declared).

Practical mapping into `cop_points`:

1. Use **SCOP (average climate)** as the COP anchor around **+7 °C**.
2. Choose a lower COP at negative temperature and a higher COP at mild temperature.
3. Keep values plausible and monotonic (COP increases with outdoor temperature).

Example from your shown Hisense label:

- Heating SCOP values shown: **5.3** (warmer), **4.6** (average), colder not declared.
- Good initial `cop_points` set for HybridHeat:
  - `-7:2.8, 0:3.6, 7:4.6, 12:5.0`

Why this works:

- `7:4.6` is aligned with the declared **average-climate SCOP 4.6**.
- Lower temperatures get lower COP (`-7`, `0`).
- Mild temperatures get higher COP (`12`), but still below/around warm-climate seasonal behavior.

Fine-tuning later:

- If HybridHeat prefers AC too often in cold weather, lower the cold points (e.g. `-7`).
- If HybridHeat prefers primary heating too often in mild weather, raise warm points slightly.
- Best accuracy comes from measured data (power + heat output), but SCOP-based points are a solid start.

## Cost logic (short)

- **Gas heat (per kWh useful heat):** `gas_heat_cost = gas_price / heating_efficiency`
- **AC heat:** `ac_heat_cost = effective_electricity_price / COP(T_outdoor)`
- **AC cool (diagnostics / same curve):** same formula is used as a **rough** marginal electricity cost per kWh of cooling; tuning is still via the configured COP points.
- **Effective electricity:** blend of grid and feed-in tariff weighted by a **PV surplus factor** (0…1) from forecast minus load. PV is **not** treated as “free”; export opportunity cost is at least the feed-in value.

## Virtual climate behaviour

- MVP modes: **`off`**, **`heat`**, **`cool`** (structure can later add **`auto`**, `TODO`).
- In **`cool`**, child AC setpoint is **hybrid target minus** the configured AC offset (in **`heat`** it is target **plus** offset).
- Extra attributes include: `active_source` (`heating` / `ac` / `none`), cost estimates, `effective_electricity_price`, `pv_surplus_expected`, `battery_soc`, `decision_reason`, plus the **`hh_*`** / **`hh_temperature_inputs`** fields described under MVP features.

**Child `climate` entities** receive `climate.turn_on` / `set_hvac_mode` / `set_temperature` only when the **logical command** (virtual mode, target, and engine decision fingerprint) **changes**—not on every 60 s poll—so devices are not pinged repeatedly when nothing changed.

## Manual testing (checklist)

1. **Heat:** Set virtual mode **heat**, target above room temperature — expect primary or AC to run per decision; `hvac_action` **heating** when a source is active.  
2. **Cool:** With an AC that lists **`cool`** in Developer Tools → States (`hvac_modes`), set mode **cool**, target below room temp — expect AC in cool; `hvac_action` **cooling** when the engine applies cool.  
3. **Off:** Virtual **off** — both child climates should go **off**.  
4. **AC without cool:** If the configured AC has a non-empty `hvac_modes` without `cool`, the virtual entity should **not** offer **cool**; switching via service should raise a clear error. If `hvac_modes` is missing/empty, **cool** may still appear until the device reports modes — a failed `set_hvac_mode` is logged with a hint to check `hvac_modes`. **New install:** when the AC state already lists modes without `cool`, the config flow shows a **menu** (pick another AC or continue heat-only).  
5. **Mode change:** After **heat** ↔ **cool** ↔ **off**, confirm no stale run (wrong child still on) using child entity states.  
6. **Restart:** Set virtual **off**, restart Home Assistant (with Recorder / restore state enabled) — virtual mode should return **off**; children should be driven off on first coordinator cycle.

## Known MVP limitations

- No MPC, no learned thermal model.  
- **Cooling** uses only the AC; **COP** for cool is the same interpolated curve as for heat (approximation).  
- **Battery** is not charged/discharged by this integration.  
- **Forecast** parsing is simple — use a **template sensor** in front of unusual entities.  
- One entry per room (shared settings are synced across all room entries via options flow).  
- **Restored** `hvac_mode` / target depend on Home Assistant’s **restore state**; if that store is empty (fresh install, Recorder off), defaults apply until you change the thermostat again.

## Roadmap / TODOs

- **Single shared storage** for global settings (today: duplicated per entry + options sync + new-room pre-fill).  
- More **options-flow fields** where HA’s schema serialization allows (e.g. battery SoC / house power selectors).  
- **`auto`** mode / comfort extras.  
- Richer **forecast / time series** handling.  
- Unit tests for `engine` without Home Assistant.

## Quality

- Runs **locally**; no cloud dependency.  
- Clear split: **models → engine → platform code**.  
- Typed Python, readable comments, explicit **TODO** markers for extensions.
