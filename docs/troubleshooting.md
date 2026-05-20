# Troubleshooting

## Sensors show `0` or `unknown` right after install

The first poll only knows about birds in the current 1-hour window. The longer-range sensors fill in as polls accumulate data:

- `recent_detections`, `last_detection`, `notable_species` — populate on the first poll that returns detections (≤ 10 minutes after install).
- `daily_top_species`, `daily_count` — populate within 24 hours as the rolling window fills.
- `yearly_top_species` — populated by a one-time yearly-baseline fetch on first setup, then refreshed once per calendar day.
- `rarest_species` — needs ≥ 7 days of poll data to compute rarity over its full window; partial results appear sooner.
- `new_species` — every species the box hears is "new" until your `seen_species` store has recorded it once. Expect the lifetime counter to climb quickly for the first few days, then stabilise.

## `last_detection` / `notable_species` are `unknown` after restart

Pre-0.4.0, both sticky sensors reset to `unknown` on every HA restart and only recovered when a fresh detection arrived. From 0.4.0 onwards their last value is persisted to `.storage/haikubox.<serial>.sticky` and rehydrated on startup, so they survive restarts (and quiet windows).

If you're on 0.4.0+ and they're still `unknown` after a restart, it means no detection has been recorded yet on this install — feed the integration a poll's worth of data and they'll populate.

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
