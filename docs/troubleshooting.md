# Troubleshooting

## Config flow rejects the serial number

The integration calls `GET https://api.haikubox.com/haikubox/<serial>` to validate your serial during setup, and the error message tells you which kind of failure it was:

- **"No shared Haikubox found for that serial..."** — the API answered but rejected the lookup (a wrong serial, or a box that isn't shared). This is the common case; the two causes below cover it.
- **"Could not reach the Haikubox API. Check your internet connection..."** — the request never got an answer at all (a network/transport failure). That points at connectivity on the HA host, not your serial or sharing setting.

The endpoint returns device info for *publicly shareable* boxes and an HTTP non-200 for everything else, so any non-200 becomes the "No shared Haikubox found" message and only a true transport error becomes "Could not reach the Haikubox API."

Two common causes of the "No shared Haikubox found" rejection:

1. **Wrong serial.** The serial is a hexadecimal code whose length varies by model (e.g. `100000003d7c9f2b`). The reliable place to read it is your public URL, shown once sharing is enabled (see below) — `https://birds.haikubox.com/listen/<serial>`. Some units also have it printed on the base, but newer ones may not.

2. **Box is private.** By default a Haikubox is **not** shareable — even with the correct serial, the API will reject the lookup. Make it shareable:
   1. Log into [listen.haikubox.com](https://listen.haikubox.com).
   2. Turn on the **"Share your haikubox with friends"** setting. Once enabled, the site will start showing your public URL (`https://birds.haikubox.com/listen/<serial>`) — that's both a confirmation the toggle took effect *and* a convenient way to read your serial off the screen.
   3. Re-run the **Add Integration** flow in Home Assistant.

The integration only reads from the public API, so the sharing setting is required for the integration to function at all.

Don't be confused by the nearby **"Make Private: Hide this Haikubox on the map"** toggle on the same settings page — that controls whether your box shows up on the public birds.haikubox.com map and has **no effect** on API access. You can leave it set either way without breaking this integration. The toggle that matters for HA is **"Share your haikubox with friends"**.

## Sensors show `0` or `unknown` right after install

Every poll fetches a 24-hour detection window from the Haikubox API, so most sensors populate on poll 1 if your box has any recent activity. A few have a longer fill horizon — here's what to expect:

- `recent_detections` — populates on the first poll that returns any detections in the last hour. Empty between active hours.
- `last_detection`, `notable_species`, `new_species` — populate on the first poll that returns detections in the last 24 hours, so within ~10 minutes of install if your box is active. `last_detection` then persists (rolling event cache, survives restarts/outages) and `new_species` persists (lifetime log); `notable_species` is an observation window and goes `unknown` after 24 h with nothing detected.
- `daily_top_species`, `daily_count` — populate on the first poll from the full 24-hour API response. The trailing window slides every poll; counts rise and fall as old detections age past 24h and new ones arrive.
- `yearly_top_species` — the top species over a rolling 12-month window, built from per-day `/daily-count` history. On a fresh install it starts from the first backfilled chunk, then fills in over the next hour or two as the historical backfill walks back (~30 days/poll until the trailing year is covered, then slower for older history — throttled to be kind to the API). Rarity-derived sensors (`notable_species`, `rarest_species`) sharpen as that window fills.
- `rarest_species` — derived from the same per-day history; its 7-day window is available as soon as the backfill has fetched the last week (typically the first poll, which grabs ~30 days).
- `lifetime_species_count` starts at the 24-hour bootstrap count and climbs as new species come in. Bootstrap-seeded species use their **earliest** dt in that first 24-hour window as `first_seen` (not the most recent — the real first observation we can see). Truly new species detected later get exact first-seen timestamps from their actual detection events.

## `last_detection` / `notable_species` are `unknown`

These two behave differently on purpose (see #62):

- **`last_detection`** persists — it reads a rolling cache of the most recent detection events (`.storage/haikubox.<serial>.recent_events`), rehydrated on startup, so it survives HA restarts *and* box outages. "The last detection" is the last detection regardless of age. It's only `unknown` before the box's very first detection; if it's `unknown` on an established box, check HA logs.
- **`notable_species`** is deliberately *not* persisted — it means "most notable species observed in the last 24 h", so it correctly drops to `unknown` (with the bird-off icon) when nothing has been detected in 24 h. During a connectivity/hardware outage that's the expected signal — check the Haikubox app to confirm the box is actually hearing birds.

## Custom cards don't appear in the dashboard editor

The integration registers `haikubox-bird-card` and `haikubox-bird-list-card` automatically on startup; you don't need to add them as Lovelace resources.

If the card picker doesn't list them after install:

1. Restart Home Assistant once. Card registration runs during integration setup.
2. Hard-refresh your dashboard (browser reload bypassing cache, e.g. **⇧⌘R** / **Ctrl-F5**). HACS-served JS is cached aggressively.
3. Check **Settings → System → Logs** for `haikubox` setup errors — if setup failed, the cards never got registered.

## Cards show the placeholder bird (🐦) after upgrading the integration

If an HA dashboard tab was open during an integration upgrade, you may see `haikubox-bird-card` swap from real photos to the 🐦 placeholder for sensors that were rendering normally before. This is one-time post-upgrade behaviour, not a hardware or data issue.

**Why it happens.** Some releases change which attributes a sensor exposes (for example, 0.5.0 moved `image_url` / `scientific_name` / `sp_code` / `last_seen` off the top-level attributes of `last_detection` / `notable_species` / `new_species` and into the per-record `detections` list). The integration version-busts its card JS URL on every release so the browser will fetch the new JS on the next page load — but an *already-open* dashboard tab keeps running the prior version's JS until it reloads. When that older JS reads the attribute layout the upgraded integration is producing, it doesn't find what it expects, and the card's empty-state fallback renders instead of the photo.

**Fix.** Hard-refresh the dashboard once (**⇧⌘R** / **Ctrl-F5**). One-time per browser per major upgrade.

## Sensor entity IDs don't match the docs

The IDs above assume the default device name **"Bird Shazam"**. If your box has a different name, sensors are prefixed with `sensor.<your_device_name>_*` — for example `sensor.backyard_box_last_detection`. The suffix (`last_detection`, `notable_species`, etc.) is stable across installs.

## Upgrading from 0.3.x

0.4.0 is a breaking release. Most 0.3.x entities are migrated automatically by a one-time unique-id shim — your history is preserved — but the `daily_species` sensor was removed and is not migrated. Re-point any automations or dashboards that referenced it at `daily_top_species` (which exposes the same ranked list under the new `detections` contract).
