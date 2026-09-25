# Custom cards

The integration comes with two dashboard cards. They install themselves, so there's nothing to add under dashboard resources.

- [`haikubox-bird-card`](#haikubox-bird-card) shows one bird: photo, name and how long ago it was heard.
- [`haikubox-bird-list-card`](#haikubox-bird-list-card) shows a ranked list of birds. Tap a row for details.
- [Dashboard example](#dashboard-example)
- [Visual editor](#visual-editor)
- [Theming](#theming)
- [Troubleshooting](#troubleshooting)

Both cards need Home Assistant 2025.4 or later, the same as the integration.

---

## `haikubox-bird-card`

Shows a single bird with its photo, common and scientific names, and how long ago it was heard.

```yaml
type: custom:haikubox-bird-card
entity: sensor.bird_shazam_notable_species
grid_options:
  columns: 6
  rows: 4
```

The card adjusts to whatever size you give it:

- **Tall or square cards** put the photo on top and the text underneath. On short cards the photo gets shorter to make room for the text.
- **Wide cards** (wider than 3:2) put the photo on the left and the text on the right.
- **Text size** grows and shrinks with the card, so a big card can be read from across the room.

You can resize the card from the **Layout** tab in the card editor, or with `grid_options` in YAML.

The card works with any Haikubox sensor that has a `detections` list: `recent_detections`, `last_detection`, `daily_top_species`, `notable_species`, `new_species`, `yearly_top_species`, `rarest_species` and `watched_species`. It shows the top-ranked bird from that list. If the list is empty, the card says "No recent detections."

The "5m ago" label updates every minute, so it stays accurate between polls.

### Buttons on the photo

Two round buttons sit on top of the photo:

- **▶** plays the bird's call, if a recording is available. It only appears if you've turned on audio in the integration's options (see [Play the call](#play-the-call-audio)). Hide it with `show_audio: false`.
- **ⓘ** opens a popup with the same details view the list card uses: a larger photo, the Wikipedia description and reference links. Hide it with `show_details: false`.

### Showing a different bird (`position`)

The card normally shows the #1 bird. Set `position` to show a different one: `1` is the top, `2` is second, and so on. This lets you stack a few cards that each show a different bird from the same sensor:

```yaml
# The top three birds of the last 24 hours
- type: custom:haikubox-bird-card
  entity: sensor.bird_shazam_daily_top_species
  position: 1
- type: custom:haikubox-bird-card
  entity: sensor.bird_shazam_daily_top_species
  position: 2
- type: custom:haikubox-bird-card
  entity: sensor.bird_shazam_daily_top_species
  position: 3
```

If there aren't that many birds in the list, the card shows its empty message. `position` is also in the visual editor.

### `last_detection` is different

Most sensors list one record per species. `last_detection` lists individual detections, so a card pointed at it shows the single most recent detection. It keeps showing it through restarts and outages. See [sensors.md](sensors.md#one-record-per-species-or-per-detection) for details.

Since `last_detection` never goes blank, it can't tell you the box has stopped working. For that, watch for `notable_species` going `unknown`, `recent_detections` staying at 0, or the [`extended_silence`](sensors.md#binary_sensorextended_silence) binary sensor.

### Tap action

What happens when you tap the card:

- `more-info` (the default) opens the sensor's more-info dialog.
- `show-list` opens a popup with the full list for the same sensor (see below).
- `navigate` goes to another dashboard page.
- `url` opens a web page.
- `none` does nothing.

`navigation_path` and `url_path` can include these tokens, which are filled in from the bird the card is showing:

| Token | Replaced with | Example |
|--|--|--|
| `{species}` | Common name | `Downy Woodpecker` |
| `{species_slug}` | Common name with underscores for spaces | `Downy_Woodpecker` |
| `{sp_code}` | eBird species code | `dowwoo` |
| `{scientific_name}` | Scientific name | `Picoides pubescens` |

Open the bird's eBird page:

```yaml
type: custom:haikubox-bird-card
entity: sensor.bird_shazam_last_detection
tap_action:
  action: url
  url_path: https://ebird.org/species/{sp_code}
```

Open the bird's All About Birds page, which uses the underscore form of the name:

```yaml
type: custom:haikubox-bird-card
entity: sensor.bird_shazam_last_detection
tap_action:
  action: url
  url_path: https://www.allaboutbirds.org/guide/{species_slug}
```

Tokens work with `navigate` too:

```yaml
type: custom:haikubox-bird-card
entity: sensor.bird_shazam_notable_species
tap_action:
  action: navigate
  navigation_path: /lovelace-birds/species#{species}
```

#### `show-list`

`show-list` opens a popup with the [list card](#haikubox-bird-list-card) for the same sensor. Click outside the popup or press **Esc** to close it.

```yaml
type: custom:haikubox-bird-card
entity: sensor.bird_shazam_notable_species
tap_action:
  action: show-list
```

`show-list` isn't a standard Home Assistant action, so the card editor uses its own tap action dropdown instead of the usual one. Writing `tap_action` in YAML works the same either way.

---

## `haikubox-bird-list-card`

A ranked list of birds. Tap a row to expand it. Works with any sensor that has a [`detections` list](sensors.md#the-detections-attribute).

```yaml
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_yearly_top_species
title: Top Species (Last 12 Months)   # optional; defaults to the sensor's name
top: 10                        # how many birds to show (default 10)
row_size: small                # small, medium or large (default small)
show_ebird: false              # eBird button on each row (default false)
show_allaboutbirds: false      # All About Birds button on each row (default false)
show_macaulay: false           # Macaulay Library button on each row (default false)
show_description: true         # Wikipedia description when a row is expanded (default true)
show_audio: true               # play button when a row is expanded (default true)
grid_options:
  columns: 12
  rows: 4                      # card height; the list scrolls if it's longer
```

Each row shows the bird's rank, photo, and common and scientific names. Tap a row to expand it into a larger photo, a short Wikipedia description, how many times it was heard, when it was last heard, and links to eBird, All About Birds and the Macaulay Library. Tap again to close it. Only one row is open at a time.

### Row size

`row_size` makes the rows bigger or smaller: `small` (the default), `medium` or `large`. Larger rows are easier to read from a distance but fit fewer birds. The expanded view is the same size either way.

```yaml
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_daily_top_species
title: Top species (today)
row_size: large
```

### Reference links

Expanded rows always show links to the bird's page on eBird, All About Birds and the Macaulay Library. Links open in a new tab.

If you'd like the buttons on every row without expanding it, turn on `show_ebird`, `show_allaboutbirds` and `show_macaulay`. That works well on a wide card. On a narrow card the buttons wrap under the name.

```yaml
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_rarest_species
title: Rarest species (7 d)
show_ebird: true
show_allaboutbirds: true
show_macaulay: true
```

### Species description

An expanded row shows the first few lines of the bird's Wikipedia article. Tap the description to open the full article. Turn it off with `show_description: false`. That also removes the card's only link to Wikipedia.

### Play the call (audio)

When a recording is available, an expanded row shows a **▶ Play call** button, and the bird card shows a play button on the photo. Hide either with `show_audio: false`.

Audio is off by default because it downloads and processes recordings. Turn it on in **Settings → Devices & Services → Haikubox → Configure → Audio: enable 'play the call'**.

Once it's on:

- Haikubox's links to recordings expire after about an hour, so the integration saves a copy of each clip under `config/haikubox/audio/<serial>/`.
- Clips for the last detection and notable species are kept for 30 days. To keep clips for every detection, set **Audio: extra days to cache the full feed** to more than 0.
- Detection clips are often very quiet, so each one is turned up (normalized) when it's saved.
- A clip with no real sound in it gets no play button.

This uses `ffmpeg`, which comes with Home Assistant.

> **No sound in Safari?** Safari's default autoplay setting, "Stop Media with Sound", silences the cards. The progress bar moves but you won't hear anything. To fix it, go to **Safari → Settings for This Website…** and set Auto-Play to **Allow All Auto-Play** for your Home Assistant address. Chrome, Firefox and the Home Assistant app aren't affected.

More examples:

```yaml
# Top species (last 12 months)
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_yearly_top_species
title: Top Species (Last 12 Months)
top: 20
grid_options:
  columns: 12
  rows: 6

# Top species (today)
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_daily_top_species
title: Top species (today)
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

# recent_detections, notable_species and new_species work too
```

---

## Dashboard example

A three-column page using the sections layout:

```yaml
type: sections
title: Bird Details
sections:
  - type: grid
    cards:
      - type: custom:haikubox-bird-list-card
        entity: sensor.bird_shazam_yearly_top_species
        title: Top Species (Last 12 Months)
        top: 20
  - type: grid
    cards:
      - type: custom:haikubox-bird-list-card
        entity: sensor.bird_shazam_daily_top_species
        title: Top species (today)
        top: 10
  - type: grid
    cards:
      - type: custom:haikubox-bird-list-card
        entity: sensor.bird_shazam_rarest_species
        title: Rarest species (7 d)
        top: 10
```

---

## Visual editor

You don't have to write YAML. Click **Add card**, pick a Haikubox card, and set the options in the editor.

The entity picker only lists Haikubox sensors that have a `detections` list. Sensors that are just a number, like `daily_count` or `activity_level`, aren't offered.

The bird card's editor includes a tap action dropdown (More info, Show species list, Navigate, Open URL, None) with a path field for Navigate and Open URL. The tokens from [Tap action](#tap-action) work there too.

---

## Theming

The cards use Home Assistant's standard theme variables, so themes and `card_mod` work as usual:

| Variable | Used for |
|--|--|
| `--ha-card-border-radius` | Card and photo corners |
| `--primary-text-color` | Species name |
| `--secondary-text-color` | Scientific name, times, rank |
| `--secondary-background-color` | Photo placeholder and small labels |
| `--divider-color` | Lines between list rows, and the scrollbar |
| `--scrollbar-thumb-color` | List scrollbar (falls back to `--divider-color`) |
| `--primary-color` | Keyboard focus outline |
| `--disabled-text-color` | "No data yet" message |

---

## Troubleshooting

### "No recent detections" or a blank card

The card shows the first bird in its sensor's `detections` list. If the list is empty, the card says so instead of showing an old bird.

Why a list might be empty:

- **`last_detection`**: only before the box's first ever detection. If it's empty on a box that's been running a while, check the Home Assistant logs.
- **`notable_species`**: nothing heard in 24 hours. Your box may be offline.
- **`daily_top_species`**: nothing heard yet today.
- **`recent_detections`**: nothing heard in the last hour. Normal at night.
- **`new_species`**: only on a brand-new install if Haikubox couldn't be reached on the first poll. Check the logs.

To see exactly what the card sees, go to **Developer Tools → States**, find the sensor, and look at its `detections` attribute.

### Photos show 🐦 instead of the bird

The 🐦 placeholder means the photo didn't load. Photos are saved in `/config/haikubox/`. If that folder was deleted, it fills back up as the box hears each species again. If there's no saved copy, the card loads the photo from Haikubox's servers instead, so you'll only see 🐦 when both fail.

### "Custom element doesn't exist" after a restart

See [troubleshooting.md](troubleshooting.md#cards-show-custom-element-doesnt-exist-after-a-restart).

### The Configure button is missing

Settings like the notability slider are in the integration's options, not the card editor: **Settings → Devices & Services → Haikubox → Configure**. If the button isn't there, reload the integration (**⋮ → Reload**) or restart Home Assistant.

### The card didn't update after an upgrade

Browsers cache the card code. The integration changes the card's URL on every release to get around this, but if the card still looks old, force a refresh (Cmd/Ctrl + Shift + R) in each browser and app you use.

### The editor's entity picker is empty

The picker only shows Haikubox sensors. If it's empty, check **Settings → Devices & Services** to make sure the Haikubox integration loaded.
