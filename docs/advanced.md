# Advanced configuration

## Tuning windows and cadence

The integration's window lengths and poll cadence have sensible defaults that suit most boxes, but all four are exposed under **Settings → Devices & Services → Haikubox → Configure → Advanced** (a collapsed section — defaults are fine, change only if you know you want to). Changing an option reloads the entry, so new values take effect on the next poll.

| Option | Default | Range | What it changes |
| --- | --- | --- | --- |
| **Recent window** | 1 hour | 1–24 h | How far back `recent_detections` looks, and how long a species stays "recent" before it can re-fire a new/unusual/watched device trigger. Longer = a fuller recent list but fewer repeat alerts. |
| **Poll interval** | 10 min | 5–60 min | How often the box is polled. Shorter is fresher but more API load (and a faster audio/backfill cadence). |
| **Rarity baseline window** | 365 days | 30–730 d | Trailing days of `/daily-count` history used to rank rarity (the `notable`/`rarest` sensors and the `rarity_score` on events). Shorter favors *seasonal* rarity; longer trends toward all-time. Rebuilt from the stored daily counts on the next poll — cheap to change. |
| **New-species momentum window** | 30 days | 7–365 d | Trailing days for the "new species" momentum sensor — how many species were first heard here within the window. Display-only; affects just that sensor. |

Under the hood the integration makes a single 24-hour `/detections` request per poll — the recent window is derived client-side from that same response. The rarity baseline is assembled from per-day `/daily-count` history: one newly-completed day is fetched per poll, plus a throttled one-time historical backfill on a fresh install.

## Polling

### Changing the polling cadence

The simplest way to change how often the box is polled is the **Poll interval** option above (5–60 minutes). For finer control — a schedule-based cadence, or polling outside that range — turn off automatic polling and drive the refresh yourself:

1. Go to **Settings → Devices & Services**, open the **Haikubox** entry, use the **⋮** menu → **System options**, and turn **off** *"Enable polling for updates"*. Automatic polling stops.
2. Add an automation that refreshes the data on your chosen schedule. All Haikubox sensors share one data coordinator, so updating **any one** of them refreshes them all:

```yaml
automation:
  - alias: Refresh Haikubox every 30 minutes
    triggers:
      - trigger: time_pattern
        minutes: "/30"
    actions:
      - action: homeassistant.update_entity
        target:
          entity_id: sensor.bird_shazam_last_detection
```

This is Home Assistant's built-in, integration-agnostic mechanism for a custom polling interval — see the [HA docs on polling](https://www.home-assistant.io/common-tasks/general/#defining-a-custom-polling-interval).

## Changing the serial number

If you replace your Haikubox or initially entered the wrong serial, open the integration entry under **Settings → Devices & Services**, choose **Reconfigure**, and enter the new serial. The device's entity history is preserved across the change.
