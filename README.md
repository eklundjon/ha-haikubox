# Haikubox for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2025.4+-blue.svg?logo=homeassistant)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

This is a Home Assistant integration for the [Haikubox](https://www.haikubox.com/) bird detector. It shows what your box has been hearing, keeps daily and yearly species counts, points out unusual visitors, and comes with two dashboard cards that show bird photos.

## Features

- **Recent detections.** Species heard in the last hour, updated every 10 minutes.
- **Last detection.** The most recent bird the box heard. It keeps its value through restarts and quiet spells.
- **Notable species.** The most interesting bird of the last 24 hours, scored on how rare it is at your box and how recently it was heard. You can adjust the balance between the two in the integration's options.
- **New species.** Birds heard for the first time ever on your box.
- **24-hour counts.** Total detections and top species over the last day.
- **Top species and rarest species.** The most common birds over the last 12 months and the last 24 hours, and the rarest bird of the last week.
- **Long-term history.** The integration loads your box's full daily history into Home Assistant's Statistics, so the built-in Statistics graph card can chart years of detections. No Grafana required.
- **Dashboard cards.** A single-bird photo card and a ranked list card. Tap a list row to see a bigger photo, a Wikipedia description, and links to eBird, All About Birds and the Macaulay Library.
- **Play the call.** A play button on the cards plays the detection's recording in your browser. This is off by default. Turn it on in the integration's options.
- **Automations.** Device triggers for new species, unusual visitors and species you're watching for, plus four blueprints for photo notifications and playing a call on a speaker ([one-click import](docs/automations.md#importing-a-blueprint)).
- **Watched species.** Pick birds you want to hear about and get a trigger when one shows up.
- Bird photos are cached locally, so cards keep working if the Haikubox servers are down.

## Quick start

### Install

**HACS (recommended)**

Haikubox is in the [HACS](https://hacs.xyz/) default store.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=eklundjon&repository=ha-haikubox&category=integration)

Click the badge, click **Download**, and restart Home Assistant. You can also search for **Haikubox** from inside HACS.

**Manual**

1. Copy the `custom_components/haikubox` folder into your Home Assistant `config/custom_components/` folder.
2. Restart Home Assistant.

### Turn on sharing

The integration reads from the public Haikubox API, which only knows about boxes whose owners have shared them. Sharing is off by default, so turn it on first:

1. Log in to [listen.haikubox.com](https://listen.haikubox.com).
2. Turn on **Share your haikubox with friends**.
3. The site now shows your public URL, `https://birds.haikubox.com/listen/<serial>`. Copy the serial from the end of it. It's a hex code, and its length depends on the model (for example `100000003d7c9f2b`). Some boxes have the serial printed on the base, but newer ones may not, so the URL is the safest place to get it.

### Add the integration

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Haikubox**.
3. Paste your serial number.

The integration checks the serial with Haikubox and creates a device named after your box (mine is "Bird Shazam"). Its sensors are listed in [docs/sensors.md](docs/sensors.md).

If you see *No shared Haikubox found for that serial*, check that the serial is right and that sharing is turned on. *Could not reach the Haikubox API* means Home Assistant couldn't connect to Haikubox at all. See [docs/troubleshooting.md](docs/troubleshooting.md) for more.

### Add a card

The cards install themselves, so there's nothing to add under dashboard resources. The simplest card is:

```yaml
type: custom:haikubox-bird-card
entity: sensor.bird_shazam_last_detection
```

The full card reference, including the list card and tap actions, is in [docs/cards.md](docs/cards.md).

### Long-term history

To chart your box's history, add a **Statistics graph** card. The statistic IDs use your serial in lowercase: `haikubox:box_<serial>_daily_detections` (detections per day) and `haikubox:box_<serial>_daily_species` (species per day).

```yaml
type: statistics-graph
title: Detections per day
chart_type: bar
period: day
stat_types: [change]
entities:
  - haikubox:box_<serial>_daily_detections
```

## Documentation

| Topic | Doc |
|---|---|
| Every sensor, the `detections` attribute, how rarity is scored, what's saved between restarts | [docs/sensors.md](docs/sensors.md) |
| The two cards, YAML examples, tap actions, a sample dashboard | [docs/cards.md](docs/cards.md) |
| Device triggers, the `haikubox_event` event, notification blueprints | [docs/automations.md](docs/automations.md) |
| Advanced options (windows and polling), changing the serial number | [docs/advanced.md](docs/advanced.md) |
| Setup problems, cards not loading, sensors that look empty, upgrade notes | [docs/troubleshooting.md](docs/troubleshooting.md) |
| Which Haikubox API calls the integration makes and when | [docs/api.md](docs/api.md) |
| How the code is organized | [docs/architecture.md](docs/architecture.md) |
| Development setup, tests, CI, releases | [docs/contributing.md](docs/contributing.md) |

## Attribution & data licensing

**Haikubox data and photos.** Detections, species counts and bird photos come from the Haikubox API, which is powered by [BirdNET](https://birdnet.cornell.edu/). Haikubox licenses that data under **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 (CC BY-NC-SA 4.0)**. If you use it for research, please cite BirdNET:

> Kahl, S., Wood, C. M., Eibl, M., & Klinck, H. (2021). BirdNET: A deep learning
> solution for avian diversity monitoring. *Ecological Informatics*, 61, 101236.

**Species codes.** To find photos for birds the box hasn't reported yet, the integration includes a common name → species code list derived from the **eBird/Clements Checklist v2025** (© Cornell Lab of Ornithology). The citation and terms are in [custom_components/haikubox/data/NOTICE.md](custom_components/haikubox/data/NOTICE.md).

**Non-commercial use only.** The integration's code is MIT-licensed, but both data sources above are licensed for non-commercial use only. Check those licenses before using this commercially.

## License

The code is released under the MIT License (see [LICENSE](LICENSE)). The bird data it displays is covered by the separate licenses above, not by the MIT license.

***

All product names, logos, and brands are property of their respective owners and are used here for identification purposes only. This project is not affiliated with or endorsed by Haikubox, Cornell Lab of Ornithology, or Nabu Casa.
