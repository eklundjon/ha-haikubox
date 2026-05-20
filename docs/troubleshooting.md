# Troubleshooting

## Sensors show `0` or `unknown` right after install

The first poll only knows about birds in the current 1-hour window. The longer-range sensors fill in as polls accumulate data:

- `recent_detections` — populates on the first poll that returns 1-hour detections.
- `last_detection`, `notable_species`, `new_species` — bootstrap from the 24-hour window on the first poll, so they populate within ~10 minutes of install as long as your box has detected anything in the last 24 hours.
- `daily_top_species`, `daily_count` — populate within 24 hours as the rolling window fills.
- `yearly_top_species` — populated by a one-time yearly-baseline fetch on first setup, then refreshed once per calendar day.
- `rarest_species` — needs ≥ 7 days of poll data to compute rarity over its full window; partial results appear sooner.
- `lifetime_species_count` starts at the 24-hour bootstrap count and climbs as new species come in. The bootstrap-seeded species use their 24-hour detection timestamp as `first_seen`; truly new species detected later get exact first-seen timestamps.

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

## Sensor entity IDs don't match the docs

The IDs above assume the default device name **"Bird Shazam"**. If your box has a different name, sensors are prefixed with `sensor.<your_device_name>_*` — for example `sensor.backyard_box_last_detection`. The suffix (`last_detection`, `notable_species`, etc.) is stable across installs.

## Upgrading from 0.3.x

0.4.0 is a breaking release. Most 0.3.x entities are migrated automatically by a one-time unique-id shim — your history is preserved — but the `daily_species` sensor was removed and is not migrated. Re-point any automations or dashboards that referenced it at `daily_top_species` (which exposes the same ranked list under the new `detections` contract).
