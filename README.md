# Haikubox for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.11+-blue.svg?logo=homeassistant)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Home Assistant custom integration for [Haikubox](https://www.haikubox.com/) bird audio detection devices. Surfaces recent detections, daily and yearly species counts, and highlights unusual visitors — all with bird photos and custom Lovelace cards.

## Features

- **Recent detections** — species heard in the last hour, updated every 10 minutes
- **Last detection** — persists the most recently heard bird, never goes unknown between detections
- **Notable detection** — most unusual recent bird, ranked by rarity against your box's own yearly baseline; also persists across quiet windows
- **New detection** — flags species appearing for the first time ever on your box, backed by persistent storage that survives HA restarts
- **Rolling 24-hour counts** — total detections and top species over the trailing 24 hours
- **Bird details sensors** — top species this calendar year, top species (last 24 h), and rarest species over the past 7 days
- **Custom Lovelace cards** — bird photo cards and ranked list cards with tap-to-expand detail views
- Bird photos cached locally for offline resilience

## Installation

### HACS (recommended)

1. Open HACS → **Integrations** → ⋮ → **Custom repositories**
2. Add `https://github.com/eklundjon/ha-haikubox` with category **Integration**
3. Search for **Haikubox** and install
4. Restart Home Assistant

### Manual

1. Copy the `custom_components/haikubox` folder into your HA `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Haikubox**
3. Enter the serial number from the bottom of your device (e.g. `100000003d7c9f2b`)

The integration will verify the serial against the Haikubox API and create a device named after your box (e.g. "Bird Shazam").

To change the serial number later, go to the integration entry and select **Reconfigure**.

## Entities

All entities are grouped under a single device per Haikubox. Entity IDs are prefixed with your device name (e.g. `sensor.bird_shazam_*`).

### Core sensors

| Entity | State | Notable attributes |
|---|---|---|
| `sensor.recent_detections` | Species count in current 1-hour window | `detections` (ranked by recency) |
| `sensor.last_detection` | Most recently heard species | `last_seen`, `scientific_name`, `image_url` |
| `sensor.notable_detection` | Most unusual species in the current window | `detections` (ranked by rarity); `rarity_score`, `yearly_rank` |
| `sensor.new_detection` | Most recently first-detected species | `detections` (ranked by first-seen recency), `lifetime_species_count` |
| `sensor.daily_count` | Total detections, past 24 h | — (total counter) |
| `sensor.daily_detections` | Number of species, past 24 h | `detections` (ranked by 24h count) |
| `sensor.yearly_detections` | Number of species this calendar year | `detections` (ranked by yearly count) |
| `sensor.unusual_detections` | Number of species, rolling 7 d | `detections` (ranked by rarity) |

### The `detections` contract

Every list-bearing sensor exposes its list under a single **`detections`** attribute. Each item is `{ species, scientific_name, sp_code, image_url, last_seen, rank, … }` (individual sensors also add `count`, `rarity_score`, `yearly_rank`, or `first_seen`). **`rank`** is a 1-based position assigned by *that sensor's own measure*:

| Sensor | `rank` 1 is | Basis |
|---|---|---|
| `recent_detections` | most recently heard | `last_seen` desc |
| `notable_detection` | most unusual | `rarity_score` desc |
| `new_detection` | most recently first-seen | `first_seen` desc |
| `daily_detections` | most detected in last 24 h | 24h `count` desc |
| `yearly_detections` | most detected this calendar year | yearly `count` |
| `unusual_detections` | rarest in last 7 days | `rarity_score` desc |

Any of these can drive the `haikubox-bird-list-card`. On a fresh install, `scientific_name`/`last_seen`/photos for the yearly sensor backfill over time as species pass through live detection polls; the recent/notable/7-day sensors have full metadata immediately.

### Rarity scoring

The `notable_detection` sensor and 7-day rare sensor score each species against your box's own yearly history. A species absent from the yearly top-75 scores `1.0`; the most commonly detected species scores close to `0`. This means a Cooper's Hawk scores as more unusual on a box that rarely records raptors than on one that hears them daily.

### Persistent state

`last_detection` and `notable_detection` never clear between polls. The following data is written to `.storage/` and survives HA restarts:

| Store file | Contents |
|---|---|
| `haikubox.<serial>.seen_species` | Lifetime first-detection log |
| `haikubox.<serial>.sp_codes` | Species → species code lookup |
| `haikubox.<serial>.sci_names` | Species → scientific name lookup |
| `haikubox.<serial>.last_seen` | Species → most recent detection timestamp |
| `haikubox.<serial>.yearly` | Yearly species baseline |
| `haikubox.<serial>.seven_day` | Rolling 7-day detection data |

## Custom cards

The integration registers two custom Lovelace cards automatically — no manual resource configuration required.

### `haikubox-bird-card`

Displays a single bird detection with a photo, species name, scientific name, and a relative timestamp.

```yaml
type: custom:haikubox-bird-card
entity: sensor.bird_shazam_notable_detection
grid_options:
  columns: 6
  rows: 4
```

The card is fully responsive to both width and height:

- **Portrait** — photo fills the card width up to a square (1:1), text is centred below. When space is tight, the scientific name is dropped and the photo shrinks to maintain at most a 3:2 aspect ratio.
- **Wide** — when the card is wider than 3:2, the photo moves to the left and text appears on the right.

The card ships sensible size defaults via `getGridOptions()`; resize it from the card's **Layout** tab in the dashboard editor, or set `grid_options` (`columns`, `rows`) in YAML. It adapts gracefully at any reasonable aspect ratio. (Requires Home Assistant 2024.11+ for the sections grid sizing API.)

Works with any sensor that exposes `image_url`, `scientific_name`, and `last_seen` attributes (e.g. `last_detection`, `notable_detection`).

#### Tap action

The card uses Home Assistant's standard `tap_action` schema. Supported actions: `more-info` (**default** — opens the bound sensor's dialog), `navigate`, `url`, and `none` (card is inert, the pre-0.4 behaviour).

`navigation_path` and `url_path` accept `{species}`, `{sp_code}`, and `{scientific_name}` tokens, URL-encoded and filled from the card's bound entity — so the action can be specific to the bird currently shown:

```yaml
# Open an external page for the bird currently displayed.
# Substitute whatever URL scheme the target site uses; this just
# shows token substitution.
type: custom:haikubox-bird-card
entity: sensor.bird_shazam_last_detection
tap_action:
  action: url
  url_path: https://www.google.com/search?q={scientific_name}+bird
```

```yaml
# Jump to a dashboard view, anchored to the species
type: custom:haikubox-bird-card
entity: sensor.bird_shazam_notable_detection
tap_action:
  action: navigate
  navigation_path: /lovelace-birds/species#{species}
```

The visual editor exposes a **Tap action** picker; the YAML option works with or without it.

---

### `haikubox-bird-list-card`

A ranked species list with tap-to-expand detail rows. Works with **any** list-bearing sensor — they all expose the same [`detections` contract](#the-detections-contract).

```yaml
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_yearly_detections
title: Top Species This Calendar Year   # optional; blank or omitted → entity friendly name
top: 10                        # max items to render (default: 10)
grid_options:
  columns: 12
  rows: 4                      # controls card height; list scrolls if content exceeds it
```

Each row shows the species, its `#rank` (by that sensor's own measure — see the contract table above), photo, and scientific name. Tapping a row expands it to a larger photo plus `count×` and a "last heard" timestamp where the sensor provides them.

Point it at any list-bearing sensor:

```yaml
# Yearly detections
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_yearly_detections
title: Top Species This Calendar Year
top: 20
grid_options:
  columns: 12
  rows: 6

# Daily detections (24 h)
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_daily_detections
title: Top Species (24 h)
grid_options:
  columns: 12
  rows: 4

# Unusual detections (7 d)
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_unusual_detections
title: Unusual Birds This Week
grid_options:
  columns: 12
  rows: 4

# Also valid: recent_detections, notable_detection, new_detection
```

---

## Dashboard example

A three-column details view using the sections layout:

```yaml
type: sections
title: Bird Details
sections:
  - type: grid
    cards:
      - type: custom:haikubox-bird-list-card
        entity: sensor.bird_shazam_yearly_detections
        title: Top Species This Calendar Year
        top: 20
  - type: grid
    cards:
      - type: custom:haikubox-bird-list-card
        entity: sensor.bird_shazam_daily_detections
        title: Top Species (24 h)
        top: 10
  - type: grid
    cards:
      - type: custom:haikubox-bird-list-card
        entity: sensor.bird_shazam_unusual_detections
        title: Unusual Birds This Week
        top: 10
```

## Polling

By default the integration polls the Haikubox API every **10 minutes**, requesting a 1-hour detection window plus a 24-hour window for the rolling 24 h sensors (`daily_count`, `daily_detections`). The yearly species baseline is refreshed once per calendar day.

### Changing the polling cadence

There is no per-interval setting; instead the integration honours Home Assistant's standard polling control. To run on your own schedule (for example, to poll less often and be kinder to the Haikubox cloud, or more often for near-real-time updates):

1. Go to **Settings → Devices & Services**, open the **Haikubox** entry, use the **⋮** menu → **System options**, and turn **off** *"Enable polling for updates"*. Automatic polling stops.
2. Add an automation that refreshes the data on your chosen schedule. All Haikubox sensors share one data coordinator, so updating **any one** of them refreshes them all:

```yaml
automation:
  - alias: Refresh Haikubox every 30 minutes
    triggers:
      - trigger: time_pattern
        minutes: "/30"
    actions:
      - action: homeassistant.update_entity
        target:
          entity_id: sensor.bird_shazam_last_detection
```

This is Home Assistant's built-in, integration-agnostic mechanism for a custom polling interval — see the [HA docs on polling](https://www.home-assistant.io/common-tasks/general/#defining-a-custom-polling-interval).

## License

MIT License — see [LICENSE](LICENSE) for details.
