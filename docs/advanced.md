# Options

Every option is under **Settings → Devices & Services → Haikubox → Configure**, in the sections below, in the order the form shows them. The defaults work for most boxes. Saving reloads the integration, so new values take effect right away.

Serial number and bat support aren't options. They're set with **Reconfigure** (see [the last section](#changing-the-serial-number-or-bat-support)).

## Main options

| Option | Default | Range | What it does |
| --- | --- | --- | --- |
| **Notability: % weight toward rarity** | 70% | 0–100% | How `notable_species` balances rarity against recency. 100% ranks on rarity alone, 0% on how recently each bird was heard. See [sensors.md](sensors.md) for the scoring. |
| **Unusual visitor: days unheard** | 30 days | 1–365 days | How long a species the box knows has to go unheard before it counts as an unusual visitor when it comes back. This drives the `unusual_visitor` trigger. |

## Watched species

| Option | Default | What it does |
| --- | --- | --- |
| **Watch species (detected here)** | none | Species to get a "watched species detected" trigger for, picked from what your box has heard. |
| **Also watch (one name per line)** | empty | Species your box hasn't heard yet, such as a bird you're hoping for. Use the common name exactly as the Haikubox app spells it. |

See [automations.md](automations.md) for the triggers.

## Audio

"Play the call" is off by default. When it's on, the integration downloads recent detection recordings to `config/haikubox/audio/`, turns up the quiet ones, and serves them locally, so the cards get a play button. (Haikubox's own clip links expire after about an hour, which is why they're copied.) It needs ffmpeg, which comes with Home Assistant.

| Option | Default | Range | What it does |
| --- | --- | --- | --- |
| **Enable "play the call"** | off | | The master switch. Off means no downloads, no processing and no play buttons. |
| **Extra days to cache the full feed** | 0 days | 0–90 days | Clips for the last and notable detections are always kept for 30 days. This keeps every recent clip for this many days as well. That's a heavier download, at roughly 74 KB a clip, and the cache has a hard size cap either way. |
| **Normalization target (peak)** | -3 dB | -24 to 0 dB | The peak level each clip is turned up (or down) to. Lower it if playback is too loud on your speakers. 0 dB is loudest but leaves no headroom and can clip on some outputs. |

## Advanced

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

## Changing the serial number or bat support

If you replace your Haikubox, or entered the wrong serial, go to **Settings → Devices & Services**, open the Haikubox entry, choose **Reconfigure**, and enter the new serial. Your sensor history is kept.

The same **Reconfigure** form has the **Bat support** checkbox. Turning it on adds the bat sensors and events; turning it off removes them and ignores bats. See [bats.md](bats.md).
