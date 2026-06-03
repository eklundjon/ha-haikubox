# Haikubox for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.12+-blue.svg?logo=homeassistant)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Home Assistant custom integration for [Haikubox](https://www.haikubox.com/) bird audio detection devices. Surfaces recent detections, daily and rolling 12-month species counts, and highlights unusual visitors — all with bird photos and custom Lovelace cards.

## Features

- **Recent detections** — species heard in the last hour, updated every 10 minutes
- **Last detection** — persists the most recently heard bird, never goes unknown between detections
- **Notable species** — top bird from the trailing 24 hours by a tunable blend of rarity (vs. your box's rolling 12-month baseline) and recency; the rarity ↔ recency weight is a slider in the integration's options
- **New species** — flags species appearing for the first time ever on your box; lifetime log survives restarts
- **Rolling 24-hour counts** — total detections and top species over the trailing 24 hours
- **Bird details sensors** — top species (last 12 months), top species (last 24 h), rarest species (7 d)
- **Custom Lovelace cards** — bird photo cards and ranked list cards with tap-to-expand detail views
- **Automations** — device triggers for new-species and unusual-visitor detections, plus blueprints for photo push notifications
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

**Prerequisite — enable public sharing on your Haikubox.** This integration reads from the public Haikubox API, which only exposes boxes their owner has chosen to share. Sharing is off by default; turn it on once and you're good:

1. Log in to [listen.haikubox.com](https://listen.haikubox.com).
2. Open the sharing setting and turn on **"Share your haikubox with friends"**.
3. The site will display your public URL — `https://birds.haikubox.com/listen/<serial>`. Copy the `<serial>` portion (a hex code; its length varies by model, e.g. `100000003d7c9f2b`). Some units also have it printed on the base, but newer ones may not — the public URL is the reliable source.

**Add the integration in Home Assistant:**

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Haikubox**.
3. Paste the serial number.

The integration will verify the serial against the Haikubox API and create a device named after your box (e.g. "Bird Shazam"). A set of sensors (plus an "extended silence" binary sensor) appears under that device — see [docs/sensors.md](docs/sensors.md) for the full list.

If setup fails with *"Could not reach the Haikubox API"*, double-check both: the serial is correct, and sharing is enabled. More in [docs/troubleshooting.md](docs/troubleshooting.md).

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
| Device triggers, the `haikubox_event` payload, push-notification blueprints | [docs/automations.md](docs/automations.md) |
| Custom polling cadence, changing the serial number | [docs/advanced.md](docs/advanced.md) |
| First-install backfill timing, restart behaviour, card-cache issues, 0.3.x → 0.4.x upgrade notes | [docs/troubleshooting.md](docs/troubleshooting.md) |
| Haikubox API endpoints, polling, image CDN, failure modes | [docs/api.md](docs/api.md) |
| Module map, data flow, persistence, lifecycle, custom-card registration | [docs/architecture.md](docs/architecture.md) |

## Attribution & data licensing

**Haikubox detection data & photos.** This integration surfaces data from the
Haikubox API — detections, species counts, and the bird photos served from its
image CDN — which is powered by [BirdNET](https://birdnet.cornell.edu/). Per
Haikubox, that data is licensed under **Creative Commons
Attribution-NonCommercial-ShareAlike 4.0 (CC BY-NC-SA 4.0)**. If you use
Haikubox data for research, please cite BirdNET:

> Kahl, S., Wood, C. M., Eibl, M., & Klinck, H. (2021). BirdNET: A deep learning
> solution for avian diversity monitoring. *Ecological Informatics*, 61, 101236.

**Species-code map.** To resolve a photo for species not yet seen in the live
detection sample, the integration bundles a derived `common name → species
code` map from the **eBird/Clements Checklist v2025** (© Cornell Lab of
Ornithology) — see
[custom_components/haikubox/data/NOTICE.md](custom_components/haikubox/data/NOTICE.md)
for the citation and terms.

**Non-commercial.** Both data sources above are **non-commercial**. The
integration's *code* is MIT-licensed (below), but the bird **data** it relies on
is not free for commercial use — review the licenses above before any commercial
deployment.

## License

MIT License — see [LICENSE](LICENSE) for details. This applies to the
integration's **code**. The bird data it surfaces (Haikubox / BirdNET, and the
bundled eBird-derived map) is covered by the separate licenses noted under
**Attribution & data licensing** above, not by the MIT license.
