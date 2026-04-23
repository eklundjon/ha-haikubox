# Haikubox for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A Home Assistant custom integration for [Haikubox](https://www.haikubox.com/) bird audio detection devices. Surfaces recent detections, daily and yearly species counts, and highlights unusual visitors — all with bird photos and custom Lovelace cards.

## Features

- **Recent detections** — species heard in the last hour, updated every 10 minutes
- **Last detected species** — persists the most recently heard bird, never goes unknown between detections
- **Most unusual recent detection** — ranked by rarity against your box's own yearly baseline; also persists across quiet windows
- **New species detected** — flags species appearing for the first time ever on your box, backed by persistent storage that survives HA restarts
- **Daily counts** — total detections and distinct species heard today
- **Bird details sensors** — top species this year, top species today, and rarest species over the past 7 days
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

| Entity | State | Key attributes |
|---|---|---|
| `sensor.recent_detections` | Species count in current 1-hour window | `detections` — list with `species`, `scientific_name`, `last_seen`, `rarity_score` |
| `sensor.last_detected` | Most recently heard species | `last_seen`, `scientific_name`, `image_url` |
| `sensor.notable_detection` | Most unusual species in the current window | `notable_detections` — full list sorted by rarity; `rarity_score`, `yearly_rank` |
| `sensor.new_species` | Most recently first-detected species | `new_today` list, `lifetime_species_count` |
| `sensor.daily_count` | Total detections today | `species_counts` — per-species breakdown |
| `sensor.daily_species` | Distinct species heard today | — |

### Bird details sensors

These sensors expose ranked species lists and are designed to be used with the `haikubox-bird-list-card` custom card. Each exposes its data under an `items` attribute.

| Entity | State | `items` contents |
|---|---|---|
| `sensor.top_species_this_year` | Number of species in yearly baseline | `species`, `scientific_name`, `count`, `rank`, `last_seen`, `image_url` |
| `sensor.top_species_today` | Number of species heard today | `species`, `scientific_name`, `count`, `last_seen`, `image_url` |
| `sensor.rarest_species_7_days` | Number of species in rolling 7-day window | `species`, `scientific_name`, `count`, `yearly_rank`, `last_seen`, `image_url` |

`scientific_name` and `last_seen` on yearly and daily sensors accumulate over time as species pass through detection polls. The 7-day rarity sensor has full metadata immediately.

### Rarity scoring

The `notable_detection` sensor and 7-day rare sensor score each species against your box's own yearly history. A species absent from the yearly top-75 scores `1.0`; the most commonly detected species scores close to `0`. This means a Cooper's Hawk scores as more unusual on a box that rarely records raptors than on one that hears them daily.

### Persistent state

`last_detected` and `notable_detection` never clear between polls. The following data is written to `.storage/` and survives HA restarts:

| Store file | Contents |
|---|---|
| `haikubox.<serial>.seen_species` | Lifetime first-detection log |
| `haikubox.<serial>.sp_codes` | Species → species code lookup |
| `haikubox.<serial>.sci_names` | Species → scientific name lookup |
| `haikubox.<serial>.last_seen` | Species → most recent detection timestamp |
| `haikubox.<serial>.yearly` | Yearly species baseline |
| `haikubox.<serial>.seven_day` | Rolling 7-day detection data |

## Custom cards

The integration registers three custom Lovelace cards automatically — no manual resource configuration required.

### `haikubox-bird-card`

Displays a single bird detection with a full-width photo, species name, scientific name, and a relative timestamp.

```yaml
type: custom:haikubox-bird-card
entity: sensor.bird_shazam_most_unusual_recent_detection
```

Works with any sensor that exposes `image_url`, `scientific_name`, and `last_seen` attributes (e.g. `last_detected`, `notable_detection`).

---

### `haikubox-bird-list-card`

A ranked species list with tap-to-expand detail rows. Works with all three bird details sensors.

```yaml
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_top_species_this_year
title: Top Species This Year   # optional; defaults to entity friendly name
top: 10                        # max items to render (default: 10)
max_height: 400                # optional: scrollable at this height in pixels
```

Tapping any row slides open an expanded view showing a larger photo, scientific name, and contextual metrics:

- **All lists** — detection count with period context ("47× this year", "8× today", "3× this week") and last heard timestamp
- **7-day rare list** — also shows yearly rank ("ranked #62 this year")

The badge adapts automatically — no different card type is needed for each sensor. Point it at whichever sensor you want:

```yaml
# Yearly top
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_top_species_this_year
title: Top Species This Year
top: 20
max_height: 500

# Daily top
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_top_species_today
title: Top Species Today

# 7-day rarity
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_rarest_species_7_days
title: Unusual Birds This Week
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
        entity: sensor.bird_shazam_top_species_this_year
        title: Top Species This Year
        top: 20
        max_height: 500
  - type: grid
    cards:
      - type: custom:haikubox-bird-list-card
        entity: sensor.bird_shazam_top_species_today
        title: Top Species Today
        top: 10
  - type: grid
    cards:
      - type: custom:haikubox-bird-list-card
        entity: sensor.bird_shazam_rarest_species_7_days
        title: Unusual Birds This Week
        top: 10
```

## Polling

The integration polls the Haikubox API every **10 minutes**, requesting a 1-hour detection window. The yearly species baseline is refreshed once per calendar day.

## License

MIT License — see [LICENSE](LICENSE) for details.
