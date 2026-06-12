# Automations

The integration fires Home Assistant events for noteworthy detections, exposes
them as **device triggers** in the automation editor, and ships two ready-made
**blueprints** that turn them into mobile push notifications with the bird's
photo.

## Device triggers (the easy path)

Every Haikubox device offers these triggers under **Settings → Automations →
Create → When → Device**:

| Trigger | Fires when |
| --- | --- |
| **New species detected** | A species is heard on this box for the **first time ever** — a genuine lifetime first. |
| **Unusual visitor detected** | A species the box already knows **returns after a long absence** (default 30 days unheard; see [Tuning](#tuning-the-unusual-visitor-threshold)). |
| **Watched species detected** | A species **you chose to watch** is heard. Pick the species in **Settings → Devices & Services → Haikubox → Configure** (a list of ones your box has detected, plus a free-text box for ones it hasn't yet). |

Pick the box, pick the trigger, and add whatever actions you like. The trigger
makes the detection's details available to your actions through the event data
described below.

## Blueprints (push notification in two clicks)

Four blueprints ship as starting points — three mobile notifications (one per
device trigger) plus a media-player one:

- **Haikubox — New species notification** (`new_species`) — push with the
  bird's photo, the running lifetime species count, and tap-through **action
  buttons** to eBird and Wikipedia.
- **Haikubox — Unusual visitor notification** (`unusual_visitor`) — push that
  **attaches the call recording** (so you can play it) when one is cached,
  falling back to the photo otherwise.
- **Haikubox — Watched species notification** (`watched_species`) — push with
  the bird's photo for the species you've chosen in the integration's options
  (see [Watched species](sensors.md) for the watch-list).
- **Haikubox — Play the call on a media player** — plays the detection's cached
  recording on a speaker/display; its trigger type is selectable.

Each asks which **Haikubox** to watch and either a **mobile-app device** to
notify or a **media player** to play on; titles/messages are editable.

These deliberately show off **different event features** — photo, action
buttons (`ebird_url`/`wikipedia_url`), `lifetime_species_count`, audio
attachment and media playback (`audio_url`). None of those are tied to a
particular trigger: **every `haikubox_event` carries the same fields** (see the
table below), so you can mix and match — e.g. add eBird buttons to the
unusual-visitor push, or play the call on a new species. Use the shipped
blueprints as recipes and copy the bits you want.

> **Audio caveats.** `audio_url` is a local `/haikubox/cache/...` URL, so it only resolves from
> inside your HA network, and the clips are **FLAC** — which iOS notification
> attachments may not play, and some media players don't support. It works best
> for an in-network media player that handles FLAC. (Audio must also be enabled
> in the integration options and a clip cached for that detection, or
> `audio_url` is `null`.)

### Importing a blueprint

In Home Assistant, go to **Settings → Automations & scenes → Blueprints →
Import blueprint** and paste the raw URL:

```
https://github.com/eklundjon/ha-haikubox/blob/main/blueprints/automation/haikubox/new_species_notification.yaml
https://github.com/eklundjon/ha-haikubox/blob/main/blueprints/automation/haikubox/unusual_visitor_notification.yaml
https://github.com/eklundjon/ha-haikubox/blob/main/blueprints/automation/haikubox/watched_species_notification.yaml
https://github.com/eklundjon/ha-haikubox/blob/main/blueprints/automation/haikubox/play_call_on_media_player.yaml
```

Then **Settings → Automations & scenes → Create automation → Use blueprint**,
choose the imported blueprint, and fill in the Haikubox and the device to
notify.

> The bird photo is attached as the notification image. On Android it shows
> inline; on iOS it appears when you long-press / expand the notification.

## Event reference

Under the hood all three triggers are filtered views of a single bus event,
`haikubox_event`, discriminated by its `type` field. You can also trigger on
the raw event (**When → Other → Manual event**, event type `haikubox_event`)
if you want to react to several boxes at once or match on the payload yourself.

Event data:

| Field | Description |
| --- | --- |
| `type` | `new_species`, `unusual_visitor`, or `watched_species` — which trigger this is. |
| `device_id` | HA device-registry id of the Haikubox (what the device trigger filters on). |
| `serial` | The Haikubox serial. |
| `device_name` | Friendly name of the box. |
| `species` | Bird common name. |
| `scientific_name` | Scientific name. |
| `sp_code` | eBird species code. |
| `image_url` | Photo URL for the species (may be absent). |
| `audio_url` | Local `/haikubox/cache/...` URL of the species' cached call recording, or `null` when audio is disabled or no clip is cached. Reachable only from inside your HA network (use it as a notification audio attachment). |
| `last_seen` | Timestamp of this detection. |
| `count` | Times this species was heard in the recent (1-hour) window. |
| `ebird_url` | eBird species page. |
| `wikipedia_url` | Wikipedia article. |
| `allaboutbirds_url` | All About Birds species guide. |
| `macaulay_url` | Macaulay Library media page. |
| `rarity_score` | Rarity vs. the box's rolling 12-month baseline. |
| `yearly_rank` | Rank within the rolling 12-month rarity baseline (1 = most common). The field name predates the rolling baseline and is kept for compatibility. |
| `days_absent` | **`unusual_visitor` only** — days since the previous sighting. |
| `lifetime_species_count` | **`new_species` only** — total distinct species ever detected on this box, including this one (e.g. "your 87th species"). |

In templates these are reached via `trigger.event.data.<field>` (for example
`{{ trigger.event.data.species }}`).

## Tuning the unusual-visitor threshold

`unusual_visitor` fires when a known species reappears after at least *N* days
unheard. *N* defaults to **30 days** and is set per-box in **Settings →
Devices & services → Haikubox → Configure → "Unusual visitor: days unheard."**

The threshold is built on the integration's persisted last-seen history, so it
measures the real gap since the species was last heard — independent of the
rarity baseline, which makes it a more reliable alerting signal than raw rarity.

## How the events stay quiet

The events are designed not to flood you:

- **Fresh installs are silent.** Setup pre-seeds the box's species history from
  the first 24-hour window, so bootstrapping doesn't fire a burst of
  `new_species` events for birds the box already knew about.
- **Restarts are silent for `unusual_visitor`.** The first poll of each session
  only establishes a baseline; it won't replay every long-absent bird that
  happens to be in the current window.
- **No re-firing while a bird lingers.** A species that stays present across
  several polls fires once, not on every poll, because the events trigger on the
  *edge* of a species entering the recent window.
