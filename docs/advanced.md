# Advanced configuration

## Windows and polling

The defaults work for most boxes, but you can change them under **Settings → Devices & Services → Haikubox → Configure → Advanced**. Saving reloads the integration, so new values take effect right away.

| Option | Default | Range | What it does |
| --- | --- | --- | --- |
| **Recent window** | 1 hour | 1–24 h | How far back `recent_detections` looks. It's also how long a bird has to be gone before it can set off a new/unusual/watched trigger again. A longer window gives you a longer list and fewer repeat alerts. |
| **Poll interval** | 10 min | 5–60 min | How often the integration checks with Haikubox. Shorter is fresher but makes more requests. |
| **Rarity baseline window** | 365 days | 30–730 days | How many days of history rarity is measured against. Shorter makes rarity more seasonal; longer makes it closer to all-time. Changing this doesn't download anything new. |
| **New-species momentum window** | 30 days | 7–365 days | The window for `new_species_window`. It only affects that one sensor. |

## Polling on your own schedule

The **Poll interval** option covers 5 to 60 minutes. If you want something else, like polling only during the day, turn off automatic polling and refresh from an automation instead:

1. Go to **Settings → Devices & Services**, open **Haikubox**, and choose **⋮ → System options**. Turn off **Enable polling for updates**.
2. Create an automation that updates any one Haikubox sensor on your schedule. All the sensors share the same data, so updating one refreshes them all.

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

This is standard Home Assistant. See [defining a custom polling interval](https://www.home-assistant.io/common-tasks/general/#defining-a-custom-polling-interval) in the HA docs.

## Changing the serial number

If you replace your Haikubox, or entered the wrong serial, go to **Settings → Devices & Services**, open the Haikubox entry, choose **Reconfigure**, and enter the new serial. Your sensor history is kept.
