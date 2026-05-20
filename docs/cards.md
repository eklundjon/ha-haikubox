# Custom cards

The integration registers two custom Lovelace cards automatically — no manual resource configuration required.

- [`haikubox-bird-card`](#haikubox-bird-card) — single bird, photo + species + relative timestamp
- [`haikubox-bird-list-card`](#haikubox-bird-list-card) — ranked list with tap-to-expand detail rows
- [Dashboard example](#dashboard-example) — three-column details view using the sections layout

---

## `haikubox-bird-card`

Displays a single bird detection with a photo, species name, scientific name, and a relative timestamp.

```yaml
type: custom:haikubox-bird-card
entity: sensor.bird_shazam_notable_species
grid_options:
  columns: 6
  rows: 4
```

The card is fully responsive to both width and height:

- **Portrait** — photo fills the card width up to a square (1:1), text is centred below. When space is tight, the scientific name is dropped and the photo shrinks to maintain at most a 3:2 aspect ratio.
- **Wide** — when the card is wider than 3:2, the photo moves to the left and text appears on the right.

The card ships sensible size defaults via `getGridOptions()`; resize it from the card's **Layout** tab in the dashboard editor, or set `grid_options` (`columns`, `rows`) in YAML. It adapts gracefully at any reasonable aspect ratio. (Requires Home Assistant 2024.11+ for the sections grid sizing API.)

Works with **any** Haikubox sensor: the event/sticky sensors (`last_detection`, `notable_species`, `new_species`) render the bird from their state; the list sensors (`recent_detections`, `daily_top_species`, `yearly_top_species`, `rarest_species`) render their #1 ranked bird from `detections`.

### Tap action

The card uses Home Assistant's standard `tap_action` schema. Supported actions: `more-info` (**default** — opens the bound sensor's dialog), `navigate`, `url`, and `none` (card is inert, the pre-0.4 behaviour).

`navigation_path` and `url_path` accept `{species}`, `{sp_code}`, and `{scientific_name}` tokens, URL-encoded from the bound entity's state/attributes. On the event/sticky sensors (`last_detection`/`notable_species`/`new_species`) these match the bird shown; on list sensors the tokens read the entity state/attributes, **not** the displayed #1 item — so use species-specific tap actions with the event sensors:

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
entity: sensor.bird_shazam_notable_species
tap_action:
  action: navigate
  navigation_path: /lovelace-birds/species#{species}
```

The visual editor exposes a **Tap action** picker; the YAML option works with or without it.

---

## `haikubox-bird-list-card`

A ranked species list with tap-to-expand detail rows. Works with **any** list-bearing sensor — they all expose the same [`detections` contract](sensors.md#the-detections-contract).

```yaml
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_yearly_top_species
title: Top Species This Calendar Year   # optional; blank or omitted → entity friendly name
top: 10                        # max items to render (default: 10)
grid_options:
  columns: 12
  rows: 4                      # controls card height; list scrolls if content exceeds it
```

Each row shows the species, its `#rank` (by that sensor's own measure — see the contract table), photo, and scientific name. Tapping a row expands it to a larger photo plus `count×` and a "last heard" timestamp where the sensor provides them.

Point it at any list-bearing sensor:

```yaml
# Top species (this calendar year)
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_yearly_top_species
title: Top Species This Calendar Year
top: 20
grid_options:
  columns: 12
  rows: 6

# Top species (24 h)
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_daily_top_species
title: Top Species (24 h)
grid_options:
  columns: 12
  rows: 4

# Rarest species (7 d)
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_rarest_species
title: Rarest Species (7 d)
grid_options:
  columns: 12
  rows: 4

# Also valid: recent_detections, notable_species, new_species
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
        entity: sensor.bird_shazam_yearly_top_species
        title: Top Species This Calendar Year
        top: 20
  - type: grid
    cards:
      - type: custom:haikubox-bird-list-card
        entity: sensor.bird_shazam_daily_top_species
        title: Top Species (24 h)
        top: 10
  - type: grid
    cards:
      - type: custom:haikubox-bird-list-card
        entity: sensor.bird_shazam_rarest_species
        title: Rarest species (7 d)
        top: 10
```
