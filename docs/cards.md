# Custom cards

The integration registers two custom Lovelace cards automatically — no manual resource configuration required.

- [`haikubox-bird-card`](#haikubox-bird-card) — single bird, photo + species + relative timestamp
- [`haikubox-bird-list-card`](#haikubox-bird-list-card) — ranked list with tap-to-expand detail rows
- [Dashboard example](#dashboard-example) — three-column details view using the sections layout
- [Visual editor](#visual-editor) — both cards expose a UI editor in the dashboard's card editor
- [Theming](#theming) — CSS variables both cards honour
- [Troubleshooting](#troubleshooting) — common questions

Both cards work on **Home Assistant 2025.4+** (the integration's minimum; the cards themselves only need the sections grid sizing API and modern container queries, which have been available since 2024.12).

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
- **Text scales with the card.** The species name, scientific name, and timestamp grow as the card grows (via container-query units), so a large card reads at a distance and a small one stays compact. The common name scales most aggressively; sizes are bounded so they never get comically large or unreadably small.

The card ships sensible size defaults via `getGridOptions()`; resize it from the card's **Layout** tab in the dashboard editor, or set `grid_options` (`columns`, `rows`) in YAML. It adapts gracefully at any reasonable aspect ratio.

Works with any **list-bearing** Haikubox sensor — the 8 that expose a per-species `detections` list (`recent_detections`, `last_detection`, `daily_top_species`, `notable_species`, `new_species`, `yearly_top_species`, `rarest_species`, `watched_species`). The numeric/diagnostic sensors (`daily_count`, `lifetime_species`, `species_diversity`, `activity_level`, `new_species_window`, `history_start`) have no list and aren't offered. By default the card renders the **top-ranked** record (the #1 entry by that sensor's own measure). Empty list → empty card showing "No recent detections."

The relative timestamp ("5m ago", "2h ago") refreshes every 60 seconds independently of the sensor's poll cadence, so the label stays honest between the 10-minute poll intervals.

### Showing a different rank (`position`)

By default the card shows the top-ranked bird. Set `position` (1-based) to show a different rank — `1` is the top, `2` the second, and so on. This is handy for building a **column of single-bird cards**, each surfacing a different rank from the same sensor:

```yaml
# Three stacked cards showing the top three of the last 24 hours
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

If `position` exceeds the number of detections the sensor currently has, the card shows its empty state. `position` is also available as a field in the visual editor.

### Per-event vs. per-species

Most sensors' `detections` lists are **per-species** — one record per distinct bird. The card pointed at any of these shows the species ranked #1 by that sensor's criterion (most recent, rarest, most detected, etc.).

`last_detection.detections` is the exception: it's **per-event** (one record per individual detection), read from a persisted rolling cache of the 50 most recent events. The card pointed at `last_detection` therefore shows the single most recent event and keeps showing it through restarts and outages (#62). See [sensors.md](sensors.md#per-species-vs-per-event-live-vs-cached) for details.

`last_detection` no longer blanks on an outage — its rolling cache keeps the last detection regardless of age. The "box has gone silent" signal is instead **`notable_species` going `unknown`** (nothing notable in 24 h) or **`recent_detections` reading 0** — usually a hardware or connectivity problem worth investigating.

### Tap action

Supported actions: `more-info` (**default** — opens the bound sensor's dialog), `show-list` (opens a popup of the full species list for this sensor — see below), `navigate`, `url`, and `none` (card is inert).

`navigation_path` and `url_path` accept four tokens, URL-encoded from the displayed record (the one selected by `position`) — so the action always targets the bird the user is looking at, on any sensor:

| Token | Substituted with | Use case |
|--|--|--|
| `{species}` | Common name (e.g. `Downy Woodpecker`) | Generic search or dashboard navigation |
| `{species_slug}` | Common name with spaces → underscores (e.g. `Downy_Woodpecker`) | URL formats like allaboutbirds.org that key on the slug |
| `{sp_code}` | Four-letter species code (e.g. `dowwoo`) | eBird-style URL keys |
| `{scientific_name}` | Latin binomial (e.g. `Picoides pubescens`) | Generic search by scientific name |

Two of the Haikubox app's own external references map cleanly to these tokens:

```yaml
# Open the eBird species page for the bird currently displayed.
# eBird URLs are keyed on the species code we already carry as
# `sp_code` — one-to-one substitution, no encoding tricks needed.
type: custom:haikubox-bird-card
entity: sensor.bird_shazam_last_detection
tap_action:
  action: url
  url_path: https://ebird.org/species/{sp_code}
```

```yaml
# Open the All About Birds species page for the bird currently
# displayed. allaboutbirds.org keys URLs on the common name with
# spaces converted to underscores ("Downy_Woodpecker") — that's
# exactly what `{species_slug}` produces. Hyphenated names like
# "White-winged Dove" keep their hyphens.
type: custom:haikubox-bird-card
entity: sensor.bird_shazam_last_detection
tap_action:
  action: url
  url_path: https://www.allaboutbirds.org/guide/{species_slug}
```

Token substitution works for `navigate` actions too — e.g. jumping to a dashboard view anchored to the species name:

```yaml
type: custom:haikubox-bird-card
entity: sensor.bird_shazam_notable_species
tap_action:
  action: navigate
  navigation_path: /lovelace-birds/species#{species}
```

#### `show-list` — popup the full species list

`action: show-list` opens a modal popup containing the [`haikubox-bird-list-card`](#haikubox-bird-list-card) for the **same sensor** — a quick way to go from a single-bird summary to the full ranked list without leaving the dashboard. The popup has a backdrop and closes on click-outside or **Esc**.

```yaml
type: custom:haikubox-bird-card
entity: sensor.bird_shazam_notable_species
tap_action:
  action: show-list
```

The visual editor exposes a **Tap action** dropdown — More info / Show species list / Navigate / Open URL / None — and a path field for the navigate/url cases. (This is a Haikubox-specific picker rather than Home Assistant's standard action selector, because `show-list` is a custom action HA's selector can't list; raw `tap_action` YAML still works either way.)

---

## `haikubox-bird-list-card`

A ranked species list with tap-to-expand detail rows. Works with **any** list-bearing sensor — they all expose the same [`detections` contract](sensors.md#the-detections-contract).

```yaml
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_yearly_top_species
title: Top Species (Last 12 Months)   # optional; blank or omitted → entity friendly name
top: 10                        # max items to render (default: 10)
row_size: small                # small | medium | large (default: small)
show_ebird: false              # eBird links in compact view (default: false)
show_allaboutbirds: false      # All About Birds links in compact view (default: false)
show_macaulay: false           # Macaulay Library links in compact view (default: false)
show_description: true         # Wikipedia description in the detail view (default: true)
show_audio: true               # "Play call" button in the detail view (default: true)
grid_options:
  columns: 12
  rows: 4                      # controls card height; list scrolls if content exceeds it
```

Each row shows the species, its `#rank` (by that sensor's own measure — see the contract table), photo, and scientific name. **Tap a row** and it expands in place — the compact row is replaced by a detail view with a larger photo, the scientific name, a short Wikipedia description (tap it to open the full article), `count×` and a "last heard" timestamp where the sensor provides them, and reference links (see below). Tap again to collapse. Only one row is open at a time.

### Row size

`row_size` scales the resting (compact) rows — `small` (default, the densest), `medium`, or `large` grow the thumbnail, padding, and text together. It's also a dropdown in the visual editor. Larger sizes trade list density for legibility at a distance; the expanded detail view is the same regardless.

```yaml
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_daily_top_species
title: Top species (today)
row_size: large
```

### Reference link buttons

Each row can link out to the bird's external species page on **eBird**, **All About Birds**, and the **Macaulay Library**. The integration surfaces the URLs (all templated from the species code / common name) and the card just renders them. Links open in a new tab and don't toggle the row when clicked. (**Wikipedia** isn't a button — it's reached by tapping the description blurb in the detail view; see below.)

- **Expanded detail view — always shown.** Tap any row to expand it in place; all available reference links appear in the detail view. No configuration needed.
- **Compact row — opt-in.** `show_ebird`, `show_allaboutbirds`, and `show_macaulay` (default `false`, also toggles in the visual editor) add the buttons directly to the always-visible compact row. Handy on a wide card; leave them off on a narrow card — they wrap below the name rather than crowding it, and the links are still one tap away in the detail view.

```yaml
type: custom:haikubox-bird-list-card
entity: sensor.bird_shazam_rarest_species
title: Rarest species (7 d)
show_ebird: true            # eBird button on the compact row too
show_allaboutbirds: true    # All About Birds button on the compact row too
show_macaulay: true         # Macaulay Library button on the compact row too
```

### Species description

The detail view shows a short **Wikipedia** description, fetched on demand the first time you open a species' row (and cached for the session). Tap it — or the "Read more on Wikipedia ›" cue beneath it — to open the full article in a new tab. Turn it off with `show_description: false` (also a toggle in the visual editor); doing so also removes the only Wikipedia link from the card.

### Play the call (audio)

When a row has a cached recording, the detail view shows a **▶ Play call** button (and the bird card shows a round play button over the photo) that plays the detection's audio in the browser. Toggle the card element with `show_audio` (default on; both cards).

**Audio is off by default** — it's downloading, normalizing and caching work, so you opt in: **Settings → Devices & Services → Haikubox → Configure → "Audio: enable 'play the call'"**. Once on, Haikubox's recording URLs (which expire after ~1 hour) are downloaded to `config/haikubox/audio/<serial>/` (namespaced per box) and served as stable local copies from the integration's own static path. The **headline** detections (last + notable) are always kept for 30 days; to also cache the full recent feed, raise **"Audio: extra days to cache the full feed"** (0 = headline only). Requires `ffmpeg` (bundled with Home Assistant).

Two things to know about which rows get a button:

- Clips are **volume-normalized** (peak to −3 dB) when cached, because raw detection clips are often very quiet — without it, faint calls are inaudible.
- A clip with **no real audio** (a near-silent recording) is treated as missing and shows **no button**, rather than a button that plays silence. So a play button appears only on recent/headline rows whose clip both exists and has audible content — not on every historical row.

> **No sound in Safari?** Safari's default per-site **Auto-Play: "Stop Media with Sound"** silences the cards' in-browser playback (the playhead moves but you hear nothing). Fix it at Safari → **Settings for This Website…** (or Settings → Websites → Auto-Play) → set your Home Assistant site to **Allow All Auto-Play**. Chrome, Firefox and the HA app are unaffected.

Point it at any list-bearing sensor:

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

Both cards have a visual editor that the dashboard exposes automatically — there's no need to write YAML by hand. To use it: click **Add card** (or pencil-edit an existing one) → pick the Haikubox card type → the form on the right lets you set the entity and (for the list card) title and max items.

The entity picker is **pre-filtered to Haikubox sensors that expose a `detections` list** — so the 8 list-bearing sensors are offered, and the numeric/diagnostic ones (`daily_count`, `lifetime_species`, `species_diversity`, `activity_level`, `new_species_window`, `history_start`) are hidden. Unrelated integrations are filtered out entirely.

The single-bird card's editor also includes a **Tap action** picker (more-info / navigate / url / none); URL/navigate paths can use `{species}`, `{species_slug}`, `{sp_code}`, and `{scientific_name}` tokens — see [Tap action](#tap-action) above for the full table and examples.

---

## Theming

Both cards consume Home Assistant's standard CSS variables, so themes and `card_mod` work transparently. The variables they read:

| Variable | Used for |
|--|--|
| `--ha-card-border-radius` | Image and card corner radius |
| `--primary-text-color` | Species name |
| `--secondary-text-color` | Scientific name, timestamps, rank number |
| `--secondary-background-color` | Image placeholder background, metric chips, thumbnail fallback |
| `--divider-color` | Row separators in the list card; default scrollbar |
| `--scrollbar-thumb-color` | List-card scrollbar (falls back to `--divider-color`) |
| `--primary-color` | Focus outline on actionable elements |
| `--disabled-text-color` | "No data yet" empty-state text |

---

## Troubleshooting

### "No recent detections" / blank card

The card renders `detections[0]` from its bound entity's `detections` attribute. If the list is empty, the card shows the empty state honestly rather than substituting a stale value.

Common causes by sensor:

- **`last_detection`** — only blank before the box's very first detection; its rolling cache persists through restarts/outages, so a blank here on an established box is unexpected (check HA logs).
- **`notable_species`** — observation window; `unknown`/blank when nothing is detected in 24 h (e.g. box offline). This is the intended "box has gone silent" signal.
- **`daily_top_species`** — today's `/daily-count`; blank only before the first detection of the local day (or if that fetch is failing — check HA logs).
- **`recent_detections`** — quiet hour. Normal during a sleeping-bird stretch.
- **`new_species`** — would only be empty if `_seen_species` has never been populated (truly fresh install with API down on first poll). Look at HA logs.

(`daily_count` is a numeric total, not a list, so the cards don't accept it and the editor picker hides it.)

To inspect: **Developer Tools → States** → search for the entity → the `detections` attribute is the list the card reads.

### Images aren't loading

Each card replaces a broken image with the 🐦 placeholder automatically, so if you're seeing the placeholder it means the image URL didn't load.

- Check `/config/haikubox/` exists and contains JPEGs. If the folder was deleted, the cache will rebuild on subsequent polls as species are detected (any active species cycles through the cache within ~10 minutes).
- The cards display the **cached** local URL when available, falling back to the remote S3 URL otherwise — so the 🐦 placeholder only appears when both fail.

### "Configure" button missing for an integration option (e.g. notability slider)

That's the integration's options flow, not a card setting. It lives at **Settings → Devices & Services → Haikubox tile → Configure** — separate from the cards' editor. If the button isn't there, reload the integration (kebab menu → Reload) or restart HA so the new options flow registers.

### Card hasn't picked up the latest version after upgrade

Card JS is browser-cached. The integration appends a `?v=<version>` query bust on upgrade, but if you're still seeing old behaviour:

- Hard refresh the dashboard tab (Cmd/Ctrl + Shift + R).
- If running multiple HA dashboards / mobile apps, refresh each.

### Editor entity picker is empty

The picker is filtered to entities created by the Haikubox integration. If no entities show up, the integration probably hasn't loaded or set up an entry yet — go to **Settings → Devices & Services** and confirm the Haikubox tile is healthy.
