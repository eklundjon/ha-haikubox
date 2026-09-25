# Sensors

Each Haikubox gets one device in Home Assistant, and all of its entities live under that device. Entity IDs start with the device name, for example `sensor.bird_shazam_last_detection`.

## The sensors

| Entity | State | Useful attributes |
|---|---|---|
| `sensor.recent_detections` | Number of species heard in the last hour | `detections`, one per species, most recent first |
| `sensor.last_detection` | The most recent bird heard, however long ago. Keeps its value through restarts and outages. | `detections`, the last 50 individual detections, newest first |
| `sensor.notable_species` | The most notable bird of the last 24 hours. `unknown` if nothing was heard. | `detections` ranked by notability; `rarity_score`, `yearly_rank` |
| `sensor.new_species` | The most recent bird heard for the first time on this box | `detections`, the last 50 first-time birds; `lifetime_species_count` |
| `sensor.daily_count` | Total detections today. Resets at midnight in the box's time zone. | None |
| `sensor.daily_top_species` | Number of species heard today | `detections` ranked by today's count |
| `sensor.yearly_top_species` | Number of species heard in the last 12 months | `detections` ranked by 12-month count |
| `sensor.rarest_species` | Number of species heard in the last 7 days | `detections` ranked by rarity |
| `sensor.lifetime_species` | Number of different species the box has ever heard | None |
| `sensor.species_diversity` | Shannon diversity index (H′) for today's detections | `richness`, `evenness` |
| `sensor.activity_level` | Yesterday's detections compared to a typical day (1.0 is normal, 2.0 is twice as busy). `unknown` until there's enough history. | `as_of_date`, `day_total`, `typical_daily_count` |
| `sensor.new_species_window` | Number of species heard for the first time in the last 30 days | `days_since_new_species` |
| `sensor.history_start` | Diagnostic. The earliest day of history the integration has downloaded. | `days_recorded`, `days_span`, `backfill_complete` |
| `sensor.watched_species` | How many of your watched species the box has heard | `detections`, your watched species, most recently heard first |

### `sensor.lifetime_species`

Your box's life list: every different species it has ever heard. The number only goes up. It's recorded in Home Assistant's long-term statistics, so a history graph shows it climbing over the months. The same number is on `new_species` as the `lifetime_species_count` attribute.

### Activity and discovery sensors

These four sensors describe how busy and varied the box has been. They use Haikubox's full daily counts rather than the sample of individual detections, which only includes up to five per species.

- **`species_diversity`** is the Shannon diversity index for today. It's near 0 when one species dominates and higher when many species are heard in similar numbers. `richness` is the number of species and `evenness` (0 to 1) is how evenly detections are spread across them.
- **`activity_level`** compares the most recent full day to the average of the last 30 active days. `1.0` is a normal day, `2.0` is twice as busy and `0.5` is half. It uses completed days, so it doesn't creep up through the morning.
- **`new_species_window`** counts species heard for the first time in the last 30 days. Expect it to be high on a new install or during migration, and to settle toward 0 once the box knows the local regulars. You can change the 30 days in the [advanced options](advanced.md).
- **`history_start`** shows how far back the downloaded history goes. On a new install it moves further back each poll as history is downloaded, then stops at the day your box was installed.

## Binary sensors

| Entity | Device class | On when |
|---|---|---|
| `binary_sensor.extended_silence` | `problem` | The box hasn't reported a single detection in 24 hours |

### `binary_sensor.extended_silence`

An outdoor Haikubox almost never goes a whole day without hearing a bird. If it does, the box is usually offline, unpowered, or its microphone has failed. This sensor turns on when that happens so you can send yourself a notification.

If the integration can't reach Haikubox at all, this sensor becomes unavailable rather than turning on. See [api.md](api.md#failure-handling).

## The `detections` attribute

Every sensor with a list puts it in an attribute called `detections`. Each item looks like this:

```
{ species, scientific_name, sp_code, image_url, last_seen, rank, ... }
```

Some sensors add `count`, `rarity_score`, `yearly_rank` or `first_seen`. `rank` starts at 1 and is based on that sensor's own ordering:

| Sensor | Rank 1 is |
|---|---|
| `recent_detections` | the most recently heard species |
| `last_detection` | the most recent detection |
| `notable_species` | the most notable species |
| `new_species` | the most recent first-time species |
| `daily_top_species` | the most detected species today |
| `yearly_top_species` | the most detected species in the last 12 months |
| `rarest_species` | the rarest species of the last 7 days |

Any of these can be used with the list card.

A few things to know:

- `recent_detections` and `notable_species` only cover the last hour and the last 24 hours. If the box goes quiet, they empty out, and `notable_species` becomes `unknown`.
- `last_detection` doesn't empty out. It keeps the last 50 detections, even through restarts and outages.
- On a new install, `daily_top_species` and `yearly_top_species` may be missing some photos and scientific names at first. These fill in as the box hears each species.

### One record per species or per detection

Most sensors have one record per species. If a bird was heard five times, you get one record with `count: 5`, and `last_seen` is the most recent of the five.

`last_detection` is the exception: it has one record per detection. A bird heard five times appears five times, each with its own `last_seen`, and there's no `count`. Otherwise the records look the same, so the cards work with both.

Two lists are kept between restarts instead of being rebuilt from the latest data:

- `new_species` lists the last 50 birds heard for the first time, over the whole life of the box.
- `last_detection` lists the last 50 detections.

## How rarity is scored

`notable_species` and `rarest_species` score each bird against your own box's last 12 months. The period rolls forward every day, so scores don't jump on January 1st. The most commonly heard species scores close to 0. A species the box hasn't heard in the last 12 months scores 1.0, the same as the rarest one it has.

So a Cooper's Hawk scores as more unusual at a box that rarely hears hawks than at one that hears them every day.

## Tuning notable species

`notable_species` mixes rarity with how recently the bird was heard:

> notability = w × rarity + (1 − w) × recency

Recency is 1.0 for a bird heard right now and falls to 0 for one heard 24 hours ago. You can set `w` with the slider in **Settings → Devices & Services → Haikubox → Configure**:

- **100% rarity.** The rarest birds of the day, which don't change much.
- **0% rarity.** Whatever was heard most recently, which changes constantly.
- **70% rarity** (the default). Mostly rarity, but a bird heard a few minutes ago can push out one heard many hours ago.

Changes take effect as soon as you save.

## What's saved between restarts

`last_detection` and `new_species` are saved, so they come back after a restart. `notable_species` isn't saved on purpose: it only covers the last 24 hours, so if the box has been quiet that long it shows `unknown`.

The integration keeps these files in Home Assistant's `.storage` folder:

| File | Contents |
|---|---|
| `haikubox.<serial>.seen_species` | When each species was first heard |
| `haikubox.<serial>.sp_codes` | Species code for each species |
| `haikubox.<serial>.sci_names` | Scientific name for each species |
| `haikubox.<serial>.last_seen` | When each species was last heard |
| `haikubox.<serial>.daily_counts` | Daily species counts for the life of the box. Rarity and the 7-day rarest list come from this. |
| `haikubox.<serial>.recent_events` | The last 50 detections, for `last_detection` |
