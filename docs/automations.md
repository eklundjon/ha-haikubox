# Automations

The integration fires an event when it hears something worth knowing about. Those events show up as device triggers in the automation editor, and there are four blueprints you can import for photo notifications or playing a bird's call on a speaker.

## Device triggers

Every Haikubox device has these triggers under **Settings → Automations → Create → When → Device**:

| Trigger | Fires when |
| --- | --- |
| **New species detected** | The box hears a species for the first time ever. |
| **Unusual visitor detected** | A species the box already knows comes back after a long absence (30 days by default; see [below](#tuning-the-unusual-visitor-threshold)). |
| **Watched species detected** | The box hears one of the species you're watching for. Choose them in **Settings → Devices & Services → Haikubox → Configure**. You can pick from birds your box has heard, or type in ones it hasn't heard yet. |

Pick your box and a trigger, then add whatever actions you want. The detection's details are available to your actions (see the [event reference](#event-reference)).

## Blueprints

There are four blueprints: one notification for each trigger, plus one that plays the call on a media player.

- **Haikubox — New species notification** sends a notification with the bird's photo, your box's species count, and buttons that open eBird and Wikipedia.
- **Haikubox — Unusual visitor notification** attaches the bird's recording if there is one, and the photo if not.
- **Haikubox — Watched species notification** sends a notification with the bird's photo for the species you're watching.
- **Haikubox — Play the call on a media player** plays the bird's recording on a speaker or display. You choose which trigger starts it.

Each blueprint asks which Haikubox to use and which phone or media player to send to. You can edit the titles and messages.

The blueprints each show off different things you can do: photos, buttons, the species count, audio. Every event has the same fields, though, so you can mix and match. Want eBird buttons on the unusual visitor notification, or the call played for new species? Copy the parts you want from the other blueprints.

> **About audio.** `audio_url` is a local address, so it only works from inside your home network. The clips are FLAC files, which iPhone notifications may not play and some media players don't support. It works best with a media player at home that handles FLAC. `audio_url` is empty unless audio is turned on in the integration's options and a clip was saved for that detection.

### Importing a blueprint

Blueprints don't come with the integration. You import each one from its URL. Click a badge to open the import dialog in Home Assistant:

| Blueprint | Import |
| --- | --- |
| Haikubox — New species notification | [![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Feklundjon%2Fha-haikubox%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fhaikubox%2Fnew_species_notification.yaml) |
| Haikubox — Unusual visitor notification | [![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Feklundjon%2Fha-haikubox%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fhaikubox%2Funusual_visitor_notification.yaml) |
| Haikubox — Watched species notification | [![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Feklundjon%2Fha-haikubox%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fhaikubox%2Fwatched_species_notification.yaml) |
| Haikubox — Play the call on a media player | [![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Feklundjon%2Fha-haikubox%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fhaikubox%2Fplay_call_on_media_player.yaml) |

To do it by hand, go to **Settings → Automations & scenes → Blueprints → Import blueprint** and paste one of these:

```
https://github.com/eklundjon/ha-haikubox/blob/main/blueprints/automation/haikubox/new_species_notification.yaml
https://github.com/eklundjon/ha-haikubox/blob/main/blueprints/automation/haikubox/unusual_visitor_notification.yaml
https://github.com/eklundjon/ha-haikubox/blob/main/blueprints/automation/haikubox/watched_species_notification.yaml
https://github.com/eklundjon/ha-haikubox/blob/main/blueprints/automation/haikubox/play_call_on_media_player.yaml
```

Then go to **Settings → Automations & scenes → Create automation → Use blueprint**, pick the blueprint, and choose your Haikubox and the device to notify.

> On Android the photo shows in the notification. On iPhone you'll see it when you long-press or expand the notification.

## Event reference

All three triggers use one event, `haikubox_event`, and its `type` field says which kind it is. You can trigger on the event directly (**When → Other → Manual event**, event type `haikubox_event`) if you want one automation for several boxes or want to filter on the fields yourself.

| Field | Description |
| --- | --- |
| `type` | `new_species`, `unusual_visitor` or `watched_species` |
| `device_id` | The Haikubox's Home Assistant device ID |
| `serial` | The Haikubox serial |
| `device_name` | The box's name |
| `species` | Common name |
| `scientific_name` | Scientific name |
| `sp_code` | eBird species code |
| `image_url` | Photo URL (may be missing) |
| `audio_url` | Local URL of the saved recording, or `null` if audio is off or there's no clip. Only works from inside your home network. |
| `last_seen` | When the bird was heard |
| `count` | How many times it was heard in the last hour |
| `ebird_url` | eBird page |
| `wikipedia_url` | Wikipedia article |
| `allaboutbirds_url` | All About Birds page |
| `macaulay_url` | Macaulay Library page |
| `rarity_score` | How rare the bird is at your box over the last 12 months |
| `yearly_rank` | Where the bird ranks in the last 12 months (1 is the most common) |
| `days_absent` | `unusual_visitor` only: days since the bird was last heard |
| `lifetime_species_count` | `new_species` only: how many species your box has ever heard, including this one |

In a template, use `trigger.event.data.<field>`, for example `{{ trigger.event.data.species }}`.

## Tuning the unusual visitor threshold

**Unusual visitor** fires when a bird comes back after at least 30 days away. You can change the number of days per box in **Settings → Devices & Services → Haikubox → Configure → Unusual visitor: days unheard**.

It's based on the actual date the bird was last heard, not on rarity, so it's a more reliable thing to alert on.

## How the events stay quiet

The events are meant not to flood you:

- **A new install doesn't fire.** The integration starts by recording every bird heard in the last 24 hours, so you don't get a new species alert for each bird your box already knew.
- **A restart doesn't fire unusual visitor.** The first check after a restart only gets its bearings.
- **One alert per visit.** A bird that hangs around for an hour fires once, not every 10 minutes.
