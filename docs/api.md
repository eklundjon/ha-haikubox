# Haikubox API interactions

This page documents every network call the integration makes — the endpoints it hits, when, with what parameters, and what it does with the responses. It's intended as a reference for anyone debugging API behaviour, planning rate-limit budgets, or reasoning about offline resilience.

The integration is a one-way **cloud_polling** consumer: it reads from the public Haikubox API and the Haikubox image S3 bucket. It never writes back to the Haikubox cloud.

## Endpoints at a glance

| Endpoint | When called | Auth | Response shape |
|---|---|---|---|
| `GET https://api.haikubox.com/haikubox/<serial>` | Config flow (initial setup + reconfigure) | None | `{ "haikuboxName": "<name>", … }` |
| `GET https://api.haikubox.com/haikubox/<serial>/detections?hours=24` | Every poll, once | None | `{ "detections": [ {cn, sn, spCode, dt}, … ] }` |
| `GET https://api.haikubox.com/haikubox/<serial>/yearly-count` | First poll of each calendar day | None | `[ { "bird": "<name>", "count": <int> }, … ]` |
| `GET https://haikubox-images.s3.amazonaws.com/<sp_code>.jpeg` | Once per species, lazily | None | Binary JPEG |

All requests use Home Assistant's shared `aiohttp` session via `async_get_clientsession(hass)`. No authentication headers are sent; the serial number in the URL path is the only access token the integration provides.

Source: [`const.py`](../custom_components/haikubox/const.py) for base URLs and intervals; [`coordinator.py`](../custom_components/haikubox/coordinator.py) for poll loop; [`config_flow.py`](../custom_components/haikubox/config_flow.py) for setup; [`image_cache.py`](../custom_components/haikubox/image_cache.py) for image fetching.

## One poll cycle

```mermaid
sequenceDiagram
    autonumber
    participant HA as Home Assistant scheduler
    participant Coord as HaikuboxCoordinator
    participant API as api.haikubox.com
    participant S3 as haikubox-images S3
    participant Store as HA .storage JSON
    participant Sensors as Sensor entities

    HA->>Coord: _async_update_data() - every 10 min

    alt First call after restart
        Coord->>Store: load 7 .storage files
    end

    alt First poll of a new calendar day
        Coord->>API: GET /yearly-count
        API-->>Coord: list of bird counts
        Coord->>Store: save yearly
    end

    Coord->>API: GET /detections?hours=24
    API-->>Coord: 24-hour detections list
    Note right of Coord: filter by dt > now - 1h<br/>for the recent window

    loop For each new sp_code seen
        Coord->>S3: GET sp_code.jpeg
        S3-->>Coord: JPEG bytes
        Coord->>Store: write to /config/www/haikubox
    end

    Coord->>Store: persist any changed lookup or store
    Coord-->>Sensors: data dict for 8 sensors
    Sensors->>HA: state and attributes updated
```

Every call is made **sequentially** today — each `await` waits for the previous one. The yearly fetch and the `/detections` call could be parallelised with `asyncio.gather`; they aren't, because the Haikubox API's responsiveness has never made it worth the complexity.

## `GET /haikubox/<serial>` — device info

**Where:** [`config_flow.py:_get_device_info`](../custom_components/haikubox/config_flow.py)

Used only during the config flow (initial setup and reconfigure). The status code is the source of truth: `200` means the serial is valid; anything else surfaces as the `cannot_connect` error in the UI.

The response body is parsed for `haikuboxName`. If present, that becomes the HA device name (e.g. *"Bird Shazam"*); if missing, the integration falls back to `Haikubox <serial>`. The user can still edit the device name in HA's UI afterwards.

This endpoint is **not** polled — once the entry is created, the device name is captured into `entry.data[CONF_DEVICE_NAME]` and the endpoint is never hit again unless the user runs Reconfigure.

## `GET /haikubox/<serial>/detections?hours=24` — detection feed

**Where:** [`coordinator.py:_fetch_detections`](../custom_components/haikubox/coordinator.py)

The endpoint accepts integer `hours` in `1..24` and returns a flat list of every detection inside that trailing window. The integration calls it **once per poll**, always with `hours=24`. Everything else — the 1-hour `recent_detections` sensor, sticky updates, new-species tracking, the 7-day rarity store — is derived from that single response by filtering the raw items client-side on their `dt` timestamps.

The response passes through `_normalise_detections` ([coordinator.py](../custom_components/haikubox/coordinator.py)) which:

1. Drops the `soundscape` non-bird entries.
2. Collapses the flat list to **one record per species**, summing detection counts and keeping the latest `dt` (timestamp) as `last_seen`.
3. Re-keys API fields to internal names:

| API field | Internal field |
|---|---|
| `cn` | `species` (common name) |
| `sn` | `scientific_name` |
| `spCode` | `sp_code` |
| `dt` | `last_seen` (ISO 8601) |

Records are sorted by `last_seen` descending. Rarity scores (`rarity_score`, `yearly_rank`) are then layered on by `_apply_rarity_scores` against the cached yearly baseline.

### Deriving the recent window

A `_filter_by_dt(raw, threshold)` helper picks the raw detection items whose `dt` is at or after `now − RECENT_WINDOW_HOURS` (1 hour by default). The filtered raw list is then run through `_normalise_detections` independently of the 24-hour normalisation. **Filtering happens before normalisation** so the per-species `count` on `recent_detections` records reflects detections-in-the-last-hour, not detections-in-the-last-24-hours — the wider 24-hour `count` ends up on `daily_count` / `daily_top_species` items where it belongs.

The integration's clock and the API's `dt` timestamps both live in UTC; the filter parses `dt` with `datetime.fromisoformat` (tolerant of the `Z` suffix from Python 3.11+) and falls back to assuming UTC if no timezone is present in the string. Bad/missing `dt` values are dropped silently.

| Sensor / pipeline | Window source |
|---|---|
| `recent_detections`, sticky updates (live), recent-window new-species tracker | Recent subset (client-side filter, 1 h) |
| `daily_count`, `daily_top_species`, `notable_species`, **7-day store**, fresh-install bootstraps (sticky + `_seen_species`) | Full 24-hour normalisation |
| `last_detection.detections` (per-event log) | Full 24-hour raw payload (sorted by `dt` desc, top 50) |
| `new_species.detections` (lifetime history) | `_seen_species` log (sticky across polls and restarts) |

### Polling cost

One `/detections` call per poll, every 10 minutes → **144 detection calls per box per day**, plus the daily yearly-count fetch and per-species image fetches (write-once). Comfortably within any sensible rate budget.

## `GET /haikubox/<serial>/yearly-count` — yearly baseline

**Where:** [`coordinator.py:_fetch_yearly_count`](../custom_components/haikubox/coordinator.py)

Returns the full per-species count for the current calendar year as a flat list. The coordinator calls this at most **once per calendar day**, gated by:

```python
if self._yearly_fetched_date != today:
    ...
    self._yearly_fetched_date = today
```

After fetching, `_process_yearly_count` ([coordinator.py:425](../custom_components/haikubox/coordinator.py)) sorts by count descending and stamps each species with a 1-based `rank`. The resulting `{species → rank}` map is what rarity scoring divides by — a species ranked 50 of 200 scores `50/200 = 0.25`; an absent species scores `yearly_total/yearly_total = 1.0` (capped, tied with the rarest known species rather than overshooting it).

The yearly list is persisted to `.storage/haikubox.<serial>.yearly` so the rank lookup survives HA restarts. If the API is unreachable at restart, the persisted list rehydrates `_yearly_ranks` and `_yearly_total` in [`_load_stores`](../custom_components/haikubox/coordinator.py) — rarity scoring keeps working with stale-but-usable data.

If the API call fails inside a routine poll and a cached baseline exists (the steady-state case), the integration logs a warning and proceeds with the cached data. If the fetch fails *and* there is no cached baseline — the only realistic path is a true fresh install whose very first `/yearly-count` request errored — the poll raises `UpdateFailed` so sensors are honestly `unavailable` rather than serving rankings computed against an empty baseline. HA retries the coordinator's first refresh automatically; subsequent polls self-heal as soon as the endpoint is reachable.

## Image CDN

**Where:** [`image_cache.py`](../custom_components/haikubox/image_cache.py)

Bird photos are fetched directly from `https://haikubox-images.s3.amazonaws.com/<sp_code>.jpeg`. The S3 bucket is public; no auth.

The cache is write-once-per-species:

1. On every detection, the coordinator calls `ImageCache.async_fetch(sp_code)`.
2. If the species code is already in the in-memory `_cached` set, the local URL is returned without touching the network.
3. Otherwise, the JPEG is downloaded (`aiohttp` GET), written to `/config/www/haikubox/<sp_code>.jpeg` via `aiofiles`, and added to `_cached`.
4. The species's `image_url` is rewritten to `/local/haikubox/<sp_code>.jpeg` — served by HA's own static handler, so it works offline once cached.

If the S3 fetch fails (404, network error), `async_fetch` falls back to returning the remote S3 URL — the card shows the photo on first paint, and the next successful poll caches it. `url_for(sp_code)` (used by `_build_daily_list` / `_build_yearly_top` for non-1h-window species) applies the same fallback synchronously.

The cache directory is indexed once at integration startup (`async_init` → `_index`, single executor hop to scan `/config/www/haikubox/`). After that, every URL lookup is an in-memory set check.

## Polling cadence

| Constant | Value | Source |
|---|---|---|
| `DEFAULT_SCAN_INTERVAL` | 600 s (10 min) | [`const.py`](../custom_components/haikubox/const.py) |
| `RECENT_WINDOW_HOURS` | 1 (h) — client-side filter, not an API parameter | [`const.py`](../custom_components/haikubox/const.py) |
| `DAILY_WINDOW_HOURS` | 24 (h) | [`const.py`](../custom_components/haikubox/const.py) |

`RECENT_WINDOW_HOURS = 1` gives a 6× overlap against the 10-minute poll interval — a single missed poll never loses recent detections, because the next poll's 24-hour fetch (and 1-hour client-side filter) re-includes anything the missed poll would have seen. `DAILY_WINDOW_HOURS = 24` is the API's documented maximum; bigger windows would need server-side aggregation that the public endpoint doesn't expose.

The user can override the cadence through HA's standard "Enable polling for updates" toggle plus a time-pattern automation — see [docs/advanced.md](advanced.md).

## Failure handling

| Failure | Behaviour |
|---|---|
| `/detections` raises `aiohttp.ClientError` | `_async_update_data` raises `UpdateFailed`; HA marks sensors `unavailable` until the next successful poll |
| `/yearly-count` raises `aiohttp.ClientError`, cached baseline available | Warning logged; poll proceeds with the previously-cached yearly baseline |
| `/yearly-count` not yet cached AND endpoint fails | `UpdateFailed` raised — sensors `unavailable` until the next poll succeeds. HA retries automatically on a fresh install's first refresh |
| Image S3 fetch returns non-200 | Card falls back to the remote S3 URL; next poll retries the cache write |
| Image S3 fetch raises | Same — remote URL returned; failure is logged at DEBUG |
| `/haikubox/<serial>` (device info) returns non-200 | Config flow surfaces `cannot_connect`; entry is not created |

The integration does **not** retry within a single poll. Failed calls just wait for the next 10-minute tick — HA's coordinator does the right thing on its own.

## Diagnostics

The diagnostics download bundle ([`diagnostics.py`](../custom_components/haikubox/diagnostics.py)) includes the full coordinator data and entry data, with the serial number redacted. It's safe to attach to a bug report.
