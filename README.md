# HybridHeat – Home Assistant Custom Integration

**Kostenorientierte Hybrid-Raumheizung:** Pro Raum stellt HybridHeat eine **virtuelle `climate`-Entity** bereit. Der Nutzer stellt nur **Solltemperatur** und **Modus** (`off` / `heat`) ein. Die Integration wählt intern wirtschaftlich zwischen einer **Heizungs-Climate-Entity** (z. B. Gas/Fußbodenheizung) und einer **Klima-Climate-Entity** (Split-Gerät im Heizmodus) und steuert beide realen Geräte vorsichtig im Hintergrund.

- **Projektname:** HybridHeat  
- **Domain:** `hybrid_heat`  
- **Art:** Native **Custom Integration** (kein Add-on)

---

## Ziel und Umfang

- Eine **virtuelle Thermostat-Entity pro Raum**, die sich wie ein normales Heizthermostat bedienen lässt.
- Entscheidung **pro Zyklus** (Polling), welche physische Quelle aktiv ist – aus Sicht der **Wärmekosten pro kWh Nutzwärme** unter Berücksichtigung von:
  - Gaspreis, Netzstrompreis, Einspeisevergütung  
  - **Forecast.Solar** / PV-Prognose (als **Wirtschaftlichkeits-** und **Überschuss-Indikator**, nicht als Zimmer-Solar-Gain)  
  - optional **Batterie** (SoC, Kapazität, Grenzen – nur **Beobachtung**, keine aktive Batteriesteuerung im MVP)  
  - **COP-Kurve** der Klimaanlage über die Außentemperatur (Stützpunkte + lineare Interpolation)
- **Stabilität:** Hysterese, Mindestlaufzeiten, Mindeststillstand nach Umschalten, Kostengleichstand-Toleranz gegen häufiges Umschalten.

---

## MVP-Funktionsumfang

1. Konfiguration über **Config Flow** (UI): Raumname, Pflicht-Entities, globale Sensoren, optional Batterie/Last/COP-Text.
2. **Virtuelle Climate-Entity** mit `current_temperature`, `target_temperature`, `hvac_mode`, `hvac_action` sowie dokumentierten **Custom-Attributen** (aktive Quelle, Kosten, effektiver Strompreis, PV-Überschuss-Schätzung, Batterie-SoC falls vorhanden, Begründung).
3. **Diagnose-Sensoren** (optional aktivierbar) für Quelle, Kosten, COP, PV-Faktor, Textgrund.
4. **Heuristische Engine** (keine Mehrstunden-Optimierung): vergleicht `gas_price / η` mit `effective_electricity_price / COP`.

---

## Architekturüberblick

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

---

## Installation

Repository: [github.com/nheilemann/home-assistant-hybridheat](https://github.com/nheilemann/home-assistant-hybridheat)

### Über HACS (empfohlen)

HybridHeat ist (noch) **nicht** im Standard-Katalog von HACS. Du fügst das Repo als **Custom repository** hinzu:

1. [HACS](https://www.hacs.xyz/) in Home Assistant installieren bzw. einrichten, falls noch nicht vorhanden.
2. HACS öffnen → **Integrations** → rechts oben **⋮** (oder **Menü**) → **Custom repositories**.
3. Als URL eintragen: `https://github.com/nheilemann/home-assistant-hybridheat`  
   Kategorie: **Integration** → **Hinzufügen**.
4. Unter **Integrations** nach **HybridHeat** suchen → **Herunterladen** (Branch/Version wie gewohnt wählen).
5. Home Assistant **neu starten**.
6. **Einstellungen → Geräte & Dienste → Integration hinzufügen** → **HybridHeat** konfigurieren.

### Manuell (Custom Component)

1. Den Ordner `custom_components/hybrid_heat` aus diesem Repository nach  
   `<config>/custom_components/hybrid_heat/` kopieren (oder das Repo klonen und denselben Pfad verwenden).
2. Home Assistant neu starten.
3. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach **„HybridHeat“** suchen.

### Nach der Installation

Pro Raum einen Integrations-Eintrag anlegen (gleiche globalen Sensoren dürfen in mehreren Einträgen **wiederverwendet** werden; ein **gemeinsamer** Konfigurationsschritt für alle Räume ist noch `TODO`).

---

## Konfigurationskonzept

### Pro Raum (Pflicht)

- Heizungs-`climate`  
- Klima-`climate` (Heizmodus)  
- Raumtemperatur-`sensor`

### Global (pro Eintrag, typischerweise gleiche Entities wählen)

- Außentemperatur  
- Strompreis, Gaspreis, Einspeisevergütung  
- Ein oder mehrere Sensoren mit **erwarteter PV-Leistung** (z. B. Forecast.Solar „power now / next hour“ – je nach Installation)

### Optional

- Batterie-SoC, nutzbare Kapazität (kWh), SoC-Grenzen für die Heuristik  
- Hausleistung oder Grundlast (W)  
- COP-Stützpunkte als Text: `-5:2.2, 0:2.8, 5:3.4, 10:4.0`  
- Heizungsnutzen \(η\), Hysterese, Mindestlaufzeiten / Stillstand

**Hinweis:** Einheiten der Preise sollten konsistent sein (z. B. alle `€/kWh`); die Integration interpretiert nur **Zahlen** aus den States.

---

## Kostenlogik (Kurz)

- **Gas-Wärme (pro kWh Nutzwärme):** `gas_heat_cost = gas_price / heating_efficiency`
- **Klima-Wärme:** `ac_heat_cost = effective_electricity_price / COP(T_außen)`
- **Effektiver Strompreis:** Mischung aus Netzpreis und Einspeisevergütung, gewichtet mit einem **PV-Überschuss-Faktor** (0…1) aus Forecast minus Last. PV-Strom gilt damit **nicht** als „0 €“, sondern mit Opportunitätskosten mindestens in Höhe der Vergütung.

---

## Verhalten der virtuellen Climate-Entity

- Unterstützte Modi (MVP): **`off`**, **`heat`**. Struktur kann später um **`auto`** o. Ä. erweitert werden (`TODO`).
- Zusätzliche Attribute u. a.: `active_source` (`heating` / `ac` / `none`), geschätzte Kosten, `effective_electricity_price`, `pv_surplus_expected`, `battery_soc`, `decision_reason`.

Steuerung der Kinder-Entities erfolgt **ohne unnötige Service-Aufrufe** (Modus/Soll nur bei Abweichung).

---

## Bekannte Einschränkungen (MVP)

- Keine MPC-/Mehrstunden-Optimierung, kein thermisches Lernmodell.  
- **Kühlbetrieb** nicht vorgesehen.  
- **Batterie** wird nur in der Kostenheuristik leicht berücksichtigt, **nicht** geladen/entladen gesteuert.  
- **Forecast**-Parsing ist bewusst simpel (State-Zahl oder einige Attribute) – exotische Sensoren ggf. Template-Sensor davor schalten.  
- Ein Config-Eintrag pro Raum: **geteilte** globale Konfiguration ohne Duplikat ist noch nicht umgesetzt.  
- **Options Flow** zum Nachbearbeiten der Parameter ist noch nicht implementiert (Abbruch mit Hinweis).

---

## Roadmap / TODOs

- Gemeinsame **Globalkonfiguration** (einmal Preise/Forecast/Batterie, mehrere Räume).  
- Vollständiger **Options Flow** (Hysterese, COP, Entities tauschen).  
- Modus **`auto`** / komfortorientierte Zusatzlogik.  
- Robustere **Forecast-/Zeitreihen**-Auswertung (z. B. nächste Stunden).  
- Unit-Tests für `engine` (ohne HA-Laufzeit).  

---

## Qualität

- Lokal, keine Cloud-Pflicht.  
- Klare Trennung: **Modelle → Engine → HA-Plattform-Code**.  
- Typisiertes Python, nachvollziehbare Kommentare und markierte **TODO**-Stellen für Erweiterungen.

---

## Lizenz

Ohne Vorgabe durch das Projekt: bitte bei Veröffentlichung eine passende Open-Source-Lizenz ergänzen.
