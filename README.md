# HybridHeat – Home Assistant custom integration

**Hybrid room heating with cost-aware source selection.** HybridHeat exposes one **virtual `climate` entity per room**. You only set **target temperature** and **mode** (`off` / `heat`). The integration chooses between a **heating `climate`** (e.g. floor / gas) and an **AC `climate`** (split in heat mode) and drives both real devices conservatively in the background.

| | |
|---|---|
| **Integration domain** | `hybrid_heat` |
| **Type** | Native **custom integration** (not an add-on) |
| **Repository** | [github.com/nheilemann/home-assistant-hybridheat](https://github.com/nheilemann/home-assistant-hybridheat) |

**README:** [English](#english) · [Deutsch](#deutsch)

## License

This project is released under the **[MIT License](LICENSE)**. It is a permissive license: you may use, modify, and distribute the code with few obligations; the software is provided **as-is** without warranty. This is a common choice for Home Assistant custom components.

---

## English

### Scope and goals

- One **virtual room thermostat** that behaves like a normal heat thermostat.
- Each **polling cycle**, choose which physical heat source is active based on **marginal heat cost per kWh**, using:
  - gas price, grid electricity price, feed-in tariff  
  - **Forecast.Solar** / PV forecast (as an **economic / surplus signal**, not as solar gain into the room model)  
  - optional **battery** (SoC, capacity, limits – **observe only** in the MVP, no battery control)  
  - **COP curve** for the heat pump / AC vs outdoor temperature (support points + linear interpolation)
- **Stability:** hysteresis, minimum run times per source, minimum idle after switching, tie band to reduce flapping.

### MVP feature set

1. **Config flow** (UI): room name, required entities, global sensors, optional battery / load / COP text.
2. **Virtual `climate`** with `current_temperature`, `target_temperature`, `hvac_mode`, `hvac_action` and documented **custom attributes** (active source, cost estimates, effective power price, PV surplus hint, battery SoC if configured, decision text).
3. **Diagnostic sensors** (optional in the UI) for source, costs, COP, PV factor, reason.
4. **Heuristic engine** (no multi-hour optimisation): compares `gas_price / η` with `effective_electricity_price / COP`.

### Architecture

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

### Installation

#### Via HACS (recommended)

HybridHeat is **not** in the default HACS store. Add the repo as a **custom repository**:

1. Install and open [HACS](https://www.hacs.xyz/) in Home Assistant.
2. HACS → **Integrations** → **⋮** → **Custom repositories**.
3. URL: `https://github.com/nheilemann/home-assistant-hybridheat` — category **Integration** → **Add**.
4. Find **HybridHeat** under **Integrations** → **Download** (pick branch/version as usual).
5. **Restart** Home Assistant.
6. **Settings → Devices & services → Add integration** → set up **HybridHeat**.

#### Manual (custom component)

1. Copy `custom_components/hybrid_heat` from this repo to `<config>/custom_components/hybrid_heat/`.
2. Restart Home Assistant.
3. **Settings → Devices & services → Add integration** → **HybridHeat**.

#### After installation

Create **one config entry per room** (you may reuse the same global sensor entities across entries; a single shared global setup step is still `TODO`).

### Configuration

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

### Cost logic (short)

- **Gas heat (per kWh useful heat):** `gas_heat_cost = gas_price / heating_efficiency`
- **AC heat:** `ac_heat_cost = effective_electricity_price / COP(T_outdoor)`
- **Effective electricity:** blend of grid and feed-in tariff weighted by a **PV surplus factor** (0…1) from forecast minus load. PV is **not** treated as “free”; export opportunity cost is at least the feed-in value.

### Virtual climate behaviour

- MVP modes: **`off`**, **`heat`** (structure can later add **`auto`**, `TODO`).
- Extra attributes include: `active_source` (`heating` / `ac` / `none`), cost estimates, `effective_electricity_price`, `pv_surplus_expected`, `battery_soc`, `decision_reason`.

Child devices are only called when mode or setpoint **actually needs** to change.

### Known MVP limitations

- No MPC, no learned thermal model.  
- **Cooling** not in scope.  
- **Battery** is not charged/discharged by this integration.  
- **Forecast** parsing is simple — use a **template sensor** in front of unusual entities.  
- One entry per room: **shared** global config without duplication is `TODO`.  
- **Options flow** for post-setup edits is not implemented yet.

### Roadmap / TODOs

- Shared **global config** (prices / forecast / battery once, many rooms).  
- Full **options flow** (hysteresis, COP, swap entities).  
- **`auto`** mode / comfort extras.  
- Richer **forecast / time series** handling.  
- Unit tests for `engine` without Home Assistant.

### Quality

- Runs **locally**; no cloud dependency.  
- Clear split: **models → engine → platform code**.  
- Typed Python, readable comments, explicit **TODO** markers for extensions.

---

## Deutsch

### Ziel und Umfang

- Eine **virtuelle Thermostat-Entity pro Raum**, die sich wie ein normales Heizthermostat bedient.
- Entscheidung **pro Zyklus** (Polling), welche physische Quelle aktiv ist – aus Sicht der **Wärmekosten pro kWh Nutzwärme** unter Berücksichtigung von:
  - Gaspreis, Netzstrompreis, Einspeisevergütung  
  - **Forecast.Solar** / PV-Prognose (als **Wirtschaftlichkeits-** und **Überschuss-Indikator**, nicht als Zimmer-Solar-Gain)  
  - optional **Batterie** (SoC, Kapazität, Grenzen – nur **Beobachtung**, keine aktive Batteriesteuerung im MVP)  
  - **COP-Kurve** der Klimaanlage über die Außentemperatur (Stützpunkte + lineare Interpolation)
- **Stabilität:** Hysterese, Mindestlaufzeiten, Mindeststillstand nach Umschalten, Kostengleichstand-Toleranz gegen häufiges Umschalten.

### MVP-Funktionsumfang

1. Konfiguration über **Config Flow** (UI): Raumname, Pflicht-Entities, globale Sensoren, optional Batterie/Last/COP-Text.
2. **Virtuelle Climate-Entity** mit `current_temperature`, `target_temperature`, `hvac_mode`, `hvac_action` sowie dokumentierten **Custom-Attributen** (aktive Quelle, Kosten, effektiver Strompreis, PV-Überschuss-Schätzung, Batterie-SoC falls vorhanden, Begründung).
3. **Diagnose-Sensoren** (optional aktivierbar) für Quelle, Kosten, COP, PV-Faktor, Textgrund.
4. **Heuristische Engine** (keine Mehrstunden-Optimierung): vergleicht `gas_price / η` mit `effective_electricity_price / COP`.

### Architekturüberblick

| Modul | Rolle |
|--------|--------|
| `__init__.py` | Lifecycle, Aufbau `RoomConfig` / `GlobalSensorConfig`, Coordinator in `hass.data`. |
| `config_flow.py` | UI-Setup (ein Eintrag = ein Raum). Optionen-Flow: Platzhalter (`TODO`). |
| `coordinator.py` | `DataUpdateCoordinator`: sammelt Snapshot (Temperaturen, Preise, Forecast, Last, Batterie). |
| `models.py` | Dataclasses: Konfiguration, Mess-Snapshot, Kosten, Entscheidung. |
| `engine.py` | COP-Interpolation, effektiver Strompreis, Wärmekosten, Hysterese, Mindestlaufzeiten. |
| `climate.py` | Virtuelle `ClimateEntity`, wendet Ergebnis **defensiv** per `climate.*`-Services an. |
| `sensor.py` | Diagnose-Sensoren aus `coordinator.last_decision`. |

Die **Forecast.Solar**-Sensoren fließen nur als Schätzung ein, ob **PV-Überschuss** wahrscheinlich ist und zu welchem Anteil der nächste elektrische „Marginal‑kWh“ eher **Netzpreis** oder **entgangene Einspeisevergütung** (Opportunitätskosten) entspricht. Es gibt **keinen** direkten Eintrag von Solarstrahlung ins Raummodell.

**Hausverbrauch:** Entweder optionaler **`house_power_entity`** oder Fallback **`base_load_w`** (Grundlast) für den Abgleich Forecast vs. Verbrauch.

### Installation

Repository: [github.com/nheilemann/home-assistant-hybridheat](https://github.com/nheilemann/home-assistant-hybridheat)

#### Über HACS (empfohlen)

HybridHeat ist (noch) **nicht** im Standard-Katalog von HACS. Du fügst das Repo als **Custom repository** hinzu:

1. [HACS](https://www.hacs.xyz/) in Home Assistant installieren bzw. einrichten, falls noch nicht vorhanden.
2. HACS öffnen → **Integrations** → rechts oben **⋮** (oder **Menü**) → **Custom repositories**.
3. Als URL eintragen: `https://github.com/nheilemann/home-assistant-hybridheat`  
   Kategorie: **Integration** → **Hinzufügen**.
4. Unter **Integrations** nach **HybridHeat** suchen → **Herunterladen** (Branch/Version wie gewohnt wählen).
5. Home Assistant **neu starten**.
6. **Einstellungen → Geräte & Dienste → Integration hinzufügen** → **HybridHeat** konfigurieren.

#### Manuell (Custom Component)

1. Den Ordner `custom_components/hybrid_heat` aus diesem Repository nach  
   `<config>/custom_components/hybrid_heat/` kopieren (oder das Repo klonen und denselben Pfad verwenden).
2. Home Assistant neu starten.
3. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach **„HybridHeat“** suchen.

#### Nach der Installation

Pro Raum einen Integrations-Eintrag anlegen (gleiche globale Sensoren dürfen in mehreren Einträgen **wiederverwendet** werden; ein **gemeinsamer** Konfigurationsschritt für alle Räume ist noch `TODO`).

### Konfigurationskonzept

#### Pro Raum (Pflicht)

- Heizungs-`climate`  
- Klima-`climate` (Heizmodus)  
- Raumtemperatur-`sensor`

#### Global (pro Eintrag, typischerweise gleiche Entities wählen)

- Außentemperatur  
- Strompreis, Gaspreis, Einspeisevergütung  
- Ein oder mehrere Sensoren mit **erwarteter PV-Leistung** (z. B. Forecast.Solar „power now / next hour“ – je nach Installation)

#### Optional

- Batterie-SoC, nutzbare Kapazität (kWh), SoC-Grenzen für die Heuristik  
- Hausleistung oder Grundlast (W)  
- COP-Stützpunkte als Text: `-5:2.2, 0:2.8, 5:3.4, 10:4.0`  
- Heizungsnutzen η, Hysterese, Mindestlaufzeiten / Stillstand

**Hinweis:** Einheiten der Preise sollten konsistent sein (z. B. alle `€/kWh`); die Integration interpretiert nur **Zahlen** aus den States.

### Kostenlogik (Kurz)

- **Gas-Wärme (pro kWh Nutzwärme):** `gas_heat_cost = gas_price / heating_efficiency`
- **Klima-Wärme:** `ac_heat_cost = effective_electricity_price / COP(T_außen)`
- **Effektiver Strompreis:** Mischung aus Netzpreis und Einspeisevergütung, gewichtet mit einem **PV-Überschuss-Faktor** (0…1) aus Forecast minus Last. PV-Strom gilt damit **nicht** als „0 €“, sondern mit Opportunitätskosten mindestens in Höhe der Vergütung.

### Verhalten der virtuellen Climate-Entity

- Unterstützte Modi (MVP): **`off`**, **`heat`**. Struktur kann später um **`auto`** o. Ä. erweitert werden (`TODO`).
- Zusätzliche Attribute u. a.: `active_source` (`heating` / `ac` / `none`), geschätzte Kosten, `effective_electricity_price`, `pv_surplus_expected`, `battery_soc`, `decision_reason`.

Steuerung der Kinder-Entities erfolgt **ohne unnötige Service-Aufrufe** (Modus/Soll nur bei Abweichung).

### Bekannte Einschränkungen (MVP)

- Keine MPC-/Mehrstunden-Optimierung, kein thermisches Lernmodell.  
- **Kühlbetrieb** nicht vorgesehen.  
- **Batterie** wird nur in der Kostenheuristik leicht berücksichtigt, **nicht** geladen/entladen gesteuert.  
- **Forecast**-Parsing ist bewusst simpel (State-Zahl oder einige Attribute) – exotische Sensoren ggf. Template-Sensor davor schalten.  
- Ein Config-Eintrag pro Raum: **geteilte** globale Konfiguration ohne Duplikat ist noch nicht umgesetzt.  
- **Options Flow** zum Nachbearbeiten der Parameter ist noch nicht implementiert (Abbruch mit Hinweis).

### Roadmap / TODOs

- Gemeinsame **Globalkonfiguration** (einmal Preise/Forecast/Batterie, mehrere Räume).  
- Vollständiger **Options Flow** (Hysterese, COP, Entities tauschen).  
- Modus **`auto`** / komfortorientierte Zusatzlogik.  
- Robustere **Forecast-/Zeitreihen**-Auswertung (z. B. nächste Stunden).  
- Unit-Tests für `engine` (ohne HA-Laufzeit).

### Qualität

- Lokal, keine Cloud-Pflicht.  
- Klare Trennung: **Modelle → Engine → HA-Plattform-Code**.  
- Typisiertes Python, nachvollziehbare Kommentare und markierte **TODO**-Stellen für Erweiterungen.

### Lizenz

Siehe [MIT License](LICENSE) (englischer Standardtext). Kurz: nutzbar und weiterverteilbar mit wenigen Pflichten, **ohne Gewährleistung**.
