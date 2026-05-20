# Advanced configuration

## Polling

By default the integration polls the Haikubox API every **10 minutes**, requesting a 1-hour detection window plus a 24-hour window for the rolling 24 h sensors (`daily_count`, `daily_top_species`). The yearly species baseline is refreshed once per calendar day.

### Changing the polling cadence

There is no per-interval setting; instead the integration honours Home Assistant's standard polling control. To run on your own schedule (for example, to poll less often and be kinder to the Haikubox cloud, or more often for near-real-time updates):

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
