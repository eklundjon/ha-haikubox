# Troubleshooting

## Setup rejects my serial number

When you add the integration, it checks your serial with Haikubox. There are two possible errors:

- **No shared Haikubox found for that serial.** Haikubox answered, but doesn't know a shared box with that serial. Either the serial is wrong or the box isn't shared.
- **Could not reach the Haikubox API.** Home Assistant couldn't connect to Haikubox. Check the internet connection on your Home Assistant machine.

For *No shared Haikubox found*:

1. **Check the serial.** It's a hex code, and its length depends on the model (for example `100000003d7c9f2b`). The easiest place to find it is your public URL, `https://birds.haikubox.com/listen/<serial>`, which appears once sharing is on. Some boxes have the serial printed on the base, but newer ones may not.
2. **Turn on sharing.** Boxes aren't shared by default, and Haikubox won't answer for a box that isn't shared, even with the right serial.
   1. Log in to [listen.haikubox.com](https://listen.haikubox.com).
   2. Turn on **Share your haikubox with friends**. Your public URL appears once it's on, which confirms the setting took and shows your serial.
   3. Try adding the integration again.

The integration only uses Haikubox's public API, so sharing has to stay on for it to work.

The same page has a **Make Private: Hide this Haikubox on the map** setting. That only controls the public map at birds.haikubox.com and has no effect on this integration. The one that matters is **Share your haikubox with friends**.

## Sensors are empty right after installing

Most sensors fill in on the first poll, within about 10 minutes, as long as your box has heard something in the last 24 hours. Some take longer:

- `recent_detections` is empty during any hour the box doesn't hear anything.
- `last_detection`, `notable_species` and `new_species` fill in on the first poll if the box has heard anything in the last 24 hours.
- `daily_top_species` and `daily_count` fill in on the first poll.
- `yearly_top_species` needs your box's history. On a new install the integration downloads it a month at a time, gently enough not to hammer Haikubox's servers. The last 12 months take an hour or two. `notable_species` and `rarest_species` get more accurate as it fills in.
- `rarest_species` only needs the last week of history, which comes with the first poll.
- `lifetime_species_count` starts with the species heard in the last 24 hours and grows from there. The integration can only see back 24 hours on the first day, so a species first heard in that window gets its earliest time in that window as its "first heard" date.

## `last_detection` or `notable_species` shows `unknown`

These two behave differently:

- **`last_detection`** is kept through restarts and outages, and always shows the last bird heard, however long ago. It's only `unknown` before your box's first ever detection. If it's `unknown` on a box that has been running a while, check the Home Assistant logs.
- **`notable_species`** only looks at the last 24 hours, so it's `unknown` whenever the box hasn't heard anything in that time. That usually means the box is offline. Check the Haikubox app to see if it's still hearing birds.

## Cards don't show up in the card picker

The cards install themselves, so you don't need to add them under dashboard resources. If they aren't in the card picker after installing:

1. Restart Home Assistant. The cards are set up when the integration loads.
2. Force-refresh your browser (**⇧⌘R** or **Ctrl-F5**).
3. Look in **Settings → System → Logs** for Haikubox errors. If the integration didn't load, the cards weren't set up either.

## Cards show "Custom element doesn't exist" after a restart

Home Assistant starts serving the dashboard before integrations like this one have finished loading. A browser or the Home Assistant app that reconnects during a restart can load the dashboard in that gap, before the cards exist.

To handle this, the integration puts a small loader at `config/www/haikubox-card-loader.js` and adds it to your dashboard resources (**Settings → Dashboards → ⋮ → Resources**). The loader waits for the integration to finish loading and then brings the cards in, so they appear without a refresh. Please don't delete that resource. It's removed automatically when you remove your last Haikubox.

If you still see the error:

1. **YAML dashboards** (`lovelace: mode: yaml`) have to list the loader themselves:
   ```yaml
   lovelace:
     mode: yaml
     resources:
       - url: /local/haikubox-card-loader.js
         type: module
   ```
   Right after an upgrade, a YAML dashboard may show the old version of the cards once. A force-refresh fixes it.
2. **First restart after installing.** Home Assistant only serves files from `config/www` if that folder existed when it started. If the integration had to create it, the loader starts working after your next restart.

## Cards show 🐦 instead of photos after an upgrade

If a dashboard was open while you upgraded the integration, cards may switch to the 🐦 placeholder. The open page is still running the old card code, which doesn't understand the new version's data. Force-refresh the page (**⇧⌘R** or **Ctrl-F5**) and the photos come back.

## Entity IDs don't match the docs

The examples use my box's name, "Bird Shazam". Your sensors will be named after your box instead, for example `sensor.backyard_box_last_detection`. The end of the name (`last_detection`, `notable_species` and so on) is always the same.

## Upgrading from 0.3.x

0.4.0 renamed most sensors. Your existing sensors are moved to the new names automatically and keep their history. The exception is `daily_species`, which was removed. Change any automations or cards that used it to `daily_top_species`, which has the same list.
