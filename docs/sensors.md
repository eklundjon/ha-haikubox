# Sensors

All entities are grouped under a single device per Haikubox. Entity IDs are prefixed with your device name (e.g. `sensor.bird_shazam_*`).

## The eight sensors

| Entity | State | Notable attributes |
|---|---|---|
| `sensor.recent_detections` | Species count in current 1-hour window | `detections` (one per species, ranked by recency) |
| `sensor.last_detection` | Most recently heard species | `detections` (one per event — most recent 50 in 24 h, ranked by recency) |
| `sensor.notable_species` | Most "notable" species in the trailing 24 h | `detections` (ranked by notability — tunable blend of rarity and recency); `rarity_score`, `yearly_rank` |
| `sensor.new_species` | Most recently first-detected species | `detections` (lifetime history — most recent 50 first-seen, ranked by first-seen recency), `lifetime_species_count` |
| `sensor.daily_count` | Total detections, past 24 h | — (total counter) |
| `sensor.daily_top_species` | Number of species, past 24 h | `detections` (ranked by 24h count) |
| `sensor.yearly_top_species` | Number of species this calendar year | `detections` (ranked by yearly count) |
| `sensor.rarest_species` | Number of species, rolling 7 d | `detections` (ranked by rarity) |

## The `detections` contract

Every list-bearing sensor exposes its list under a single **`detections`** attribute. Each item is `{ species, scientific_name, sp_code, image_url, last_seen, rank, … }` (individual sensors also add `count`, `rarity_score`, `yearly_rank`, or `first_seen`). **`rank`** is a 1-based position assigned by *that sensor's own measure*:

| Sensor | `rank` 1 is | Basis |
|---|---|---|
| `recent_detections` | most recently heard | `last_seen` desc |
| `last_detection` | most recent event | `last_seen` desc |
| `notable_species` | most notable | `notability_score` desc (rarity ↔ recency blend) |
| `new_species` | most recently first-seen | `first_seen` desc |
| `daily_top_species` | most detected in last 24 h | 24h `count` desc |
| `yearly_top_species` | most detected this calendar year | yearly `count` |
| `rarest_species` | rarest in last 7 days | `rarity_score` desc |

Any of these can drive the `haikubox-bird-list-card`. `recent_detections` reads the 1-hour subset; `notable_species` reads the full 24-hour window (so its blend has room for the recency component to matter). Both sets of records come straight from the live `/detections` response and carry full metadata immediately. `daily_top_species` and `yearly_top_species` enrich `scientific_name`/`last_seen`/photos from per-species stores, so on a fresh install those backfill as species pass through detection polls; `rarest_species` fills in as its 7-day window accumulates.

### Per-species vs. per-event, live vs. sticky

The `detections` records on every sensor *except* `last_detection` are **per-species** — `_normalise_detections` collapses multiple events for the same species into one record, with `count` = events-in-window and `last_seen` = most recent event's timestamp.

`last_detection.detections` is **per-event**: one record per individual detection in the trailing 24 h, capped at the 50 most recent. The same species detected multiple times yields multiple records, each with its own `last_seen` (the event's timestamp). The field shape per record is otherwise the same as the per-species lists, so the bird-list card works pointed at either kind. `count` is omitted on per-event records (always 1).

Most lists are **live** — recomputed every poll from the current detection window, going empty during quiet periods. Two are **sticky**:

- `new_species.detections` — N most recently first-seen species across this box's entire history, sorted by `first_seen` desc. Read from the lifetime `seen_species` log, so it stays populated forever after the first species is seen.
- `last_detection.detections` — N most recent individual events from the trailing 24 h. Per-event semantic, but functionally sticky as long as anything has been detected in the last day.

## Rarity scoring

The `notable_species` and `rarest_species` sensors score each species against your box's own yearly history. A species not present in your box's yearly data scores `1.0` (capped — tied with the rarest known species rather than overshooting it); the most-detected species scores near `0`. So a Cooper's Hawk scores as more unusual on a box that rarely records raptors than on one that hears them daily.

## Notability tuning

`notable_species` blends rarity with recency:

> `notability_score = w · rarity_score + (1 − w) · recency_score`

`recency_score` is a linear decay over the trailing 24 hours — a detection happening right now scores 1.0; one at the 24-hour edge scores 0.0. The blend weight `w` is exposed as a slider in the integration's options (Settings → Integrations → Haikubox → Configure):

- **100% rarity** — pure rarity scoring. The list is dominated by the rarest species in the last day and changes slowly (low churn). Closest to the pre-tuning default.
- **0% rarity** — pure recency. The top of the list is whatever was heard most recently (high churn).
- **70% rarity** (default) — mostly rarity-driven but with enough recency influence that a fresh sighting can dethrone an old long-tail entry.

Changes to the slider take effect immediately — the coordinator refreshes the moment you save the options form, no waiting for the next 10-minute poll.

## Persistent state

`last_detection` and `notable_species` never clear between polls. They survive HA restarts (their last value is persisted to `.storage/` and rehydrated on startup), and on a fresh install they bootstrap from the 24-hour detection window on the first poll so they populate immediately rather than waiting for an active hour.

The following data is written to `.storage/` and survives HA restarts:

| Store file | Contents |
|---|---|
| `haikubox.<serial>.seen_species` | Lifetime first-detection log |
| `haikubox.<serial>.sp_codes` | Species → species code lookup |
| `haikubox.<serial>.sci_names` | Species → scientific name lookup |
| `haikubox.<serial>.last_seen` | Species → most recent detection timestamp |
| `haikubox.<serial>.yearly` | Yearly species baseline |
| `haikubox.<serial>.seven_day` | Rolling 7-day detection data |
| `haikubox.<serial>.sticky` | Last `last_detection` / `notable_species` records |
