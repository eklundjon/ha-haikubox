# Sensors

All entities are grouped under a single device per Haikubox. Entity IDs are prefixed with your device name (e.g. `sensor.bird_shazam_*`).

## The eight sensors

| Entity | State | Notable attributes |
|---|---|---|
| `sensor.recent_detections` | Species count in current 1-hour window | `detections` (ranked by recency) |
| `sensor.last_detection` | Most recently heard species | `last_seen`, `scientific_name`, `image_url` |
| `sensor.notable_species` | Most unusual species in the current window | `detections` (ranked by rarity); `rarity_score`, `yearly_rank` |
| `sensor.new_species` | Most recently first-detected species | `detections` (ranked by first-seen recency), `lifetime_species_count` |
| `sensor.daily_count` | Total detections, past 24 h | — (total counter) |
| `sensor.daily_top_species` | Number of species, past 24 h | `detections` (ranked by 24h count) |
| `sensor.yearly_top_species` | Number of species this calendar year | `detections` (ranked by yearly count) |
| `sensor.rarest_species` | Number of species, rolling 7 d | `detections` (ranked by rarity) |

## The `detections` contract

Every list-bearing sensor exposes its list under a single **`detections`** attribute. Each item is `{ species, scientific_name, sp_code, image_url, last_seen, rank, … }` (individual sensors also add `count`, `rarity_score`, `yearly_rank`, or `first_seen`). **`rank`** is a 1-based position assigned by *that sensor's own measure*:

| Sensor | `rank` 1 is | Basis |
|---|---|---|
| `recent_detections` | most recently heard | `last_seen` desc |
| `notable_species` | most unusual | `rarity_score` desc |
| `new_species` | most recently first-seen | `first_seen` desc |
| `daily_top_species` | most detected in last 24 h | 24h `count` desc |
| `yearly_top_species` | most detected this calendar year | yearly `count` |
| `rarest_species` | rarest in last 7 days | `rarity_score` desc |

Any of these can drive the `haikubox-bird-list-card`. `recent_detections` and `notable_species` come straight from the live detection feed (full metadata immediately). `daily_top_species` and `yearly_top_species` enrich `scientific_name`/`last_seen`/photos from per-species stores, so on a fresh install those backfill as species pass through detection polls; `rarest_species` fills in as its 7-day window accumulates.

## Rarity scoring

The `notable_species` and `rarest_species` sensors score each species against your box's own yearly history. A species not present in your box's yearly data scores ≈`1.0` (maximally unusual); the most-detected species scores near `0`. So a Cooper's Hawk scores as more unusual on a box that rarely records raptors than on one that hears them daily.

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
