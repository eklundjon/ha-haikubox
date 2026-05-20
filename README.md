# Haikubox for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.11+-blue.svg?logo=homeassistant)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Home Assistant custom integration for [Haikubox](https://www.haikubox.com/) bird audio detection devices. Surfaces recent detections, daily and yearly species counts, and highlights unusual visitors — all with bird photos and custom Lovelace cards.

## Features

- **Recent detections** — species heard in the last hour, updated every 10 minutes
- **Last detection** — persists the most recently heard bird, never goes unknown between detections
- **Notable species** — most unusual recent bird, ranked by rarity against your box's own yearly baseline
- **New species** — flags species appearing for the first time ever on your box; lifetime log survives restarts
- **Rolling 24-hour counts** — total detections and top species over the trailing 24 hours
- **Bird details sensors** — top species this calendar year, top species (last 24 h), rarest species (7 d)
- **Custom Lovelace cards** — bird photo cards and ranked list cards with tap-to-expand detail views
- Bird photos cached locally for offline resilience

## Quick start

### Install

**HACS (recommended)**

1. In **HACS**, open the **⋮** menu (top right) → **Custom repositories**
2. Add `https://github.com/eklundjon/ha-haikubox`, type **Integration**, then **Add**
3. Search HACS for **Haikubox**, open it, and click **Download**
4. Restart Home Assistant

**Manual**

1. Copy the `custom_components/haikubox` folder into your HA `config/custom_components/` directory
2. Restart Home Assistant

### Configure

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Haikubox**
3. Enter the serial number from the bottom of your device (e.g. `100000003d7c9f2b`)

The integration will verify the serial against the Haikubox API and create a device named after your box (e.g. "Bird Shazam"). Eight sensors appear under that device — see [docs/sensors.md](docs/sensors.md) for the full list.

### Add a card

Both custom cards register automatically — no Lovelace resource setup required. The simplest "show me a bird" card:

```yaml
type: custom:haikubox-bird-card
entity: sensor.bird_shazam_last_detection
```

Full card reference, including the ranked list card and `tap_action` configuration: [docs/cards.md](docs/cards.md).

## Documentation

| Topic | Doc |
|---|---|
| Full sensor reference, the `detections` attribute contract, rarity scoring, persistent state stores | [docs/sensors.md](docs/sensors.md) |
| Both custom cards, YAML examples, tap actions, full dashboard example | [docs/cards.md](docs/cards.md) |
| Custom polling cadence, changing the serial number | [docs/advanced.md](docs/advanced.md) |
| First-install backfill timing, restart behaviour, card-cache issues, 0.3.x → 0.4.x upgrade notes | [docs/troubleshooting.md](docs/troubleshooting.md) |
| Haikubox API endpoints, polling, image CDN, failure modes | [docs/api.md](docs/api.md) |
| Module map, data flow, persistence, lifecycle, custom-card registration | [docs/architecture.md](docs/architecture.md) |

## License

MIT License — see [LICENSE](LICENSE) for details.
