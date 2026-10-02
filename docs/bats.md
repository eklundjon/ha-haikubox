# Bats

Haikubox's bird-and-bat model hears bats as well as birds. This page covers what the integration does with them.

## Turning it on

Bat support is a checkbox when you add the Haikubox. To change it later, open the integration and choose **Reconfigure**. It's off by default.

- **On:** bats get their own sensors and events (below).
- **Off:** bats are ignored completely. They don't appear in any sensor or event. Turning it off removes the bat sensors.

Either way, **bird figures never include bats**. That covers today's detections and top species, recent and notable species, rarity, the rarest and top species lists, lifetime and new species, activity, and the long-term statistics. If your box has been hearing bats, bird counts drop when you upgrade, and the long-term statistics show a one-time step.

## Sensors

With bat support on, four sensors are added:

| Sensor | State | `detections` attribute |
|---|---|---|
| `sensor.last_bird_detection` | the most recent bird | that detection |
| `sensor.last_bat_detection` | the most recent bat | that detection |
| `sensor.bat_detections_today` | bat detections so far today | none |
| `sensor.bats_today` | bat species heard today | today's bats, by count |

"Today" is the box's local calendar day, the same as for **Detections today**, and the counts are the true daily counts. A night of bats is split at midnight, just as a day of birds is.

`sensor.last_detection` stays as it is: the most recent detection of either kind, so it shows a bat at night and a bird by day. Use the bird and bat sensors when you want only one.

Records for bats carry `"classification": "bat"`. They have no eBird, All About Birds or Macaulay Library links (those are bird references), but keep the Wikipedia link.

## Cards

For a bat list, point a list card at the bats sensor:

```yaml
type: custom:haikubox-bird-list-card
entity: sensor.bats_today
title: Bats today
```

For a bird list that stays birds-only, use any of the existing bird sensors. For a photo of the last bat, point a bird card at `sensor.last_bat_detection`.

## Automations

- **New species** and **Watched species** fire for bats as they do for birds. The event's `classification` field tells them apart. For a bat, `lifetime_species_count` counts bat species.
- **Bat activity started** (`bat_activity`) fires when bats are heard after at least 60 minutes without one. Its `count` is the number of bat detections since the previous one, and `quiet_minutes` is how long the quiet spell lasted. It doesn't fire for every bat, and it doesn't fire on the first poll after setup, when there's no earlier bat to measure from.
- **Unusual visitor** stays birds-only, because it's based on rarity.

Every `haikubox_event` now has a `classification` field, `bird` or `bat`.

## Audio

Bat recordings are ultrasonic and play as silence without processing, so the play button isn't shown for bats yet. Making them audible is planned.

## How bats are recognized

Haikubox reports bats the same way it reports birds, with no field that says which is which.

- In the detection feed, bats have six-letter species codes in capitals (`MYOTHY` for Fringed Myotis), and an unidentified bat is "Bat" with the code `batbatbat`. Bird codes are lowercase eBird codes.
- The daily counts give names only. The integration recognizes bats there from names it has seen with a bat code, "Bat", and a bundled list of the 46 North American bat species from the USGS (see [data/NOTICE.md](../custom_components/haikubox/data/NOTICE.md)).
