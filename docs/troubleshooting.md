# Troubleshooting

## Config flow rejects the serial number with "Could not reach the Haikubox API"

The integration calls `GET https://api.haikubox.com/haikubox/<serial>` to validate your serial during setup. The endpoint returns device info for *publicly shareable* boxes and `Invalid Haikubox.` (HTTP non-200) for everything else — the integration surfaces both kinds of non-200 as the generic *"Could not reach the Haikubox API — check your serial number"* error.

Two common causes:

1. **Wrong serial.** The serial is a 16-character hex string like `100000003d7c9f2b`. It's printed on the bottom of the box, and once sharing is enabled (see below) [listen.haikubox.com](https://listen.haikubox.com) also displays it as part of your public URL — `https://birds.haikubox.com/listen/<serial>`.

2. **Box is private.** By default a Haikubox is **not** shareable — even with the correct serial, the API will reject the lookup. Make it shareable:
   1. Log into [listen.haikubox.com](https://listen.haikubox.com).
   2. Turn on the **"Share your haikubox with friends"** setting. Once enabled, the site will start showing your public URL (`https://birds.haikubox.com/listen/<serial>`) — that's both a confirmation the toggle took effect *and* a convenient way to read your serial off the screen.
   3. Re-run the **Add Integration** flow in Home Assistant.

The integration only reads from the public API, so the sharing setting is required for the integration to function at all.

Don't be confused by the nearby **"Make Private: Hide this Haikubox on the map"** toggle on the same settings page — that controls whether your box shows up on the public birds.haikubox.com map and has **no effect** on API access. You can leave it set either way without breaking this integration. The toggle that matters for HA is **"Share your haikubox with friends"**.

## Sensors show `0` or `unknown` right after install

Every poll fetches a 24-hour detection window from the Haikubox API, so most sensors populate on poll 1 if your box has any recent activity. A few have a longer fill horizon — here's what to expect:

- `recent_detections` — populates on the first poll that returns any detections in the last hour. Empty between active hours.
- `last_detection`, `notable_species`, `new_species` — bootstrap from the 24-hour window on the first poll, so they populate within ~10 minutes of install as long as your box has detected anything in the last 24 hours. (They stay sticky thereafter.)
- `daily_top_species`, `daily_count` — populate on the first poll from the full 24-hour API response. The trailing window slides every poll; counts rise and fall as old detections age past 24h and new ones arrive.
- `yearly_top_species` — populated by the yearly-baseline fetch on first setup, then refreshed once per calendar day (UTC).
- `rarest_species` — full 7-day window only after the box has been running for 7 days; before then, the sensor returns whatever the partial window currently contains.
- `lifetime_species_count` starts at the 24-hour bootstrap count and climbs as new species come in. Bootstrap-seeded species use their **earliest** dt in that first 24-hour window as `first_seen` (not the most recent — the real first observation we can see). Truly new species detected later get exact first-seen timestamps from their actual detection events.

## `last_detection` / `notable_species` are `unknown`

These sticky sensors clear themselves only when there is genuinely nothing to show. From 0.4.0 onwards the integration:

- Bootstraps both sensors from the 24-hour window on the **first poll**, so a fresh install populates within ~10 minutes as long as your box has detected anything in the last 24 hours.
- Persists their last value to `.storage/haikubox.<serial>.sticky` and rehydrates on startup, so they survive HA restarts.

If they remain `unknown` after a fresh install with these in place, it usually means the box itself has not heard a recognised species recently — check the Haikubox app to confirm.

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
