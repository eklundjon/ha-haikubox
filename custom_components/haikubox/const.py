DOMAIN = "haikubox"

CONF_SERIAL = "serial"
CONF_DEVICE_NAME = "device_name"

API_BASE = "https://api.haikubox.com"
IMAGES_BASE = "https://haikubox-images.s3.amazonaws.com"

# On-disk cache for downloaded photos and audio clips. Served through the
# integration's OWN static path (registered in async_setup), NOT Home
# Assistant's /local: /local is only mounted when config/www exists at boot, so
# a fresh install would 404 every cached URL until the next restart. Serving it
# ourselves also keeps the integration out of the user's config/www. The cache
# lives at config/<CACHE_DIR_NAME>/ and is exposed at <CACHE_URL_BASE>/...
#   images: config/haikubox/<sp_code>.jpeg          → /haikubox/cache/<sp_code>.jpeg
#   audio:  config/haikubox/audio/<serial>/<cid>.flac → /haikubox/cache/audio/<serial>/<cid>.flac
CACHE_DIR_NAME = "haikubox"          # under hass.config.path(...)
CACHE_URL_BASE = "/haikubox/cache"   # static route serving the cache dir

# How often to poll the API (seconds). User-tunable via the options flow as
# CONF_SCAN_INTERVAL (in MINUTES; floor 5, ceiling 60) — HA lets users disable
# polling but not set a custom rate, so this fills that gap. Shorter = fresher
# but more API load (and faster audio/backfill cadence).
DEFAULT_SCAN_INTERVAL = 600  # 10 minutes
CONF_SCAN_INTERVAL = "scan_interval"  # stored in minutes

# Sliding window for the recent_detections sensor + the new-species
# / 7-day-store pipelines. The integration makes exactly one /detections call
# per poll (hours=DAILY_WINDOW_HOURS) and filters that response client-side by
# this many hours for the recent view — the 1-hour window was previously a
# separate API request, but every consumer of it can be derived from the 24h
# response with a timestamp filter. User-tunable via CONF_RECENT_WINDOW_HOURS
# (1–24): widens the recent_detections sensor AND the device-trigger re-alert
# window (a species won't re-fire new/unusual/watched while still inside it).
RECENT_WINDOW_HOURS = 1
CONF_RECENT_WINDOW_HOURS = "recent_window_hours"

# Rolling window for the "daily" sensors. For these we want a true trailing
# 24-hour view, so we derive it from /detections (24 is the endpoint's max)
# rather than the server-side calendar-day /daily-count. (/daily-count is used
# separately, by calendar day, to build the rarity baseline — see below.)
DAILY_WINDOW_HOURS = 24

# Cap on the per-event `detections` list exposed on the last_detection
# sensor — the N most recent individual events from the 24h payload,
# distinct from recent_detections (which is one record per species). The
# 24h payload is the natural ceiling; this is a soft cap for attribute
# size (~50 × ~250 B ≈ 12 KB, around HA's state-attribute size warning).
LAST_DETECTION_EVENT_LIMIT = 50

# Cap on the lifetime-history `detections` list exposed on the new_species
# sensor — the N most recently first-seen species from the seen_species
# log, sorted by first_seen desc. Persisted like last_detection's per-event
# buffer, but per-species (one record per first-seen species, not per event).
# Same soft attribute-size rationale as LAST_DETECTION_EVENT_LIMIT.
NEW_SPECIES_HISTORY_LIMIT = 50

# Trailing window for the "new species (N d)" momentum sensor — how many
# species were first heard on this box within the last this-many days.
# User-tunable via CONF_NEW_SPECIES_WINDOW_DAYS (display-only; affects just that
# sensor).
NEW_SPECIES_WINDOW_DAYS = 30
CONF_NEW_SPECIES_WINDOW_DAYS = "new_species_window_days"

# Notable-species tuning. notability_score is a weighted blend of rarity
# and recency: w * rarity_score + (1-w) * recency_score. The user-facing
# option is "% weight toward rarity" (0-100); 100 = pure rarity (stable,
# low churn), 0 = pure recency (dynamic, high churn), default 70 = mostly
# rarity with a small recency nudge. Recency is a linear decay over
# NOTABILITY_WINDOW_HOURS — newest event in window scores 1.0, oldest
# scores 0.0. The window matches the daily 24h window so a slider away
# from pure rarity has real dynamic range to play with.
CONF_NOTABLE_RARITY_WEIGHT = "notable_rarity_weight"
DEFAULT_NOTABLE_RARITY_WEIGHT = 70  # percent
NOTABILITY_WINDOW_HOURS = 24

# Automation events. A single bus event is fired for noteworthy detections;
# the `type` field discriminates, matching the device-automation convention
# (cf. deconz_event / bthome_ble_event). Device triggers filter on `type`.
EVENT_HAIKUBOX = "haikubox_event"
TRIGGER_NEW_SPECIES = "new_species"          # first time ever on this box
TRIGGER_UNUSUAL_VISITOR = "unusual_visitor"  # known species back after a long absence
TRIGGER_WATCHED_SPECIES = "watched_species"  # a user-chosen species was detected
TRIGGER_TYPES = (TRIGGER_NEW_SPECIES, TRIGGER_UNUSUAL_VISITOR, TRIGGER_WATCHED_SPECIES)

# watched_species: fire the watched_species trigger when one of these is heard.
# Two options-flow inputs combine into the watch set: a multi-select picked from
# species the box has already detected, plus a free-text list (one common name
# per line) for species not yet seen here (the aspirational case).
CONF_WATCHED_SPECIES = "watched_species"       # list[str] from the pick-list
CONF_WATCHED_EXTRA = "watched_species_extra"   # newline-separated free text

# Rarity baseline. Instead of the calendar-year /yearly-count endpoint (which
# resets every Jan 1 and drifts within the year), we persist per-day species
# counts from /daily-count?date=<d> and aggregate a trailing window. The store
# keeps full box-lifetime daily counts (a reusable dataset — trends, phenology,
# true first-seen); rarity sums only the trailing RARITY_WINDOW_DAYS.
# User-tunable via CONF_RARITY_WINDOW_DAYS (30–730): shorter = seasonal rarity,
# longer = all-time. Re-ranks notable_species / rarest_species; cheap to change
# (rebuilt from the stored daily counts on the next poll).
RARITY_WINDOW_DAYS = 365
CONF_RARITY_WINDOW_DAYS = "rarity_window_days"
# "Typical" daily activity for the activity-vs-typical sensor: mean detection
# total over the trailing this-many *completed* days (zero/offline days
# excluded, so it reflects a typical active day, not one dragged down by an
# outage). The sensor compares the most recent completed day against this.
ACTIVITY_BASELINE_DAYS = 30
# Throttle the one-time historical backfill so a fresh install doesn't hammer
# the API. Two-tier (days fetched per poll, walking backward): fetch the
# rarity-relevant trailing year quickly, then ease off for the deep-history
# tail (which only feeds future trend features, not rarity scoring).
RARITY_BACKFILL_CHUNK = 30   # while the trailing RARITY_WINDOW_DAYS isn't covered
HISTORY_BACKFILL_CHUNK = 10  # once rarity is covered, for the remaining lifetime
# Treat this many consecutive 404s (days that pre-date the box) while extending
# older than all known data as the pre-install floor, and stop the deep
# backfill. The count persists across polls and only the older-than-known
# extension feeds it — gaps *inside* the known date range are recorded as empty
# and never counted. Generous enough to walk through a realistic multi-day
# outage and resume on real data beyond it. (The API gives no install date to
# anchor to — see _ensure_daily_counts.)
BACKFILL_STOP_AFTER_404 = 14
# Politeness delay (seconds) between consecutive backfill requests, so a fresh
# install's chunk of historical fetches doesn't burst the API and trip a rate
# limit. On a 429/5xx we also pause backfill until the next poll (~10 min).
BACKFILL_REQUEST_DELAY = 0.25

# unusual_visitor fires when a known species reappears after at least this
# many days unheard. Built on the persisted last-seen gap, so it's immune to
# the calendar-year reset that makes raw yearly rarity unreliable as an alert
# (the reason `notable` blends in recency in the first place). Configurable
# via the options flow.
CONF_ABSENCE_DAYS = "absence_days"
DEFAULT_ABSENCE_DAYS = 30

# Detection-audio cache. /detections carries a per-detection `wav` (a short FLAC)
# as an AWS presigned URL that expires in ~1 hour, so to make "play the call"
# robust (survive expiry + restarts, and keep the signed URL out of HA state) we
# download clips to config/haikubox/audio/<serial>/ (namespaced per box, so
# each box's retention window and clip cap are independent, and removing one
# box's cache never touches another's) and serve them from the integration's
# own static path (CACHE_URL_BASE).
#
# Two tiers, to stay gentle on Haikubox's API by default:
#   * HEADLINE — always on: only the headline records (last + notable detection),
#     a couple of clips per poll, kept HEADLINE_AUDIO_DAYS.
#   * FULL — opt-in via CONF_AUDIO_CACHE_DAYS (days; default 0 = off): also cache
#     the whole recent feed for that many days (power users; far heavier download).
# MAX_AUDIO_CLIPS is a hard safety ceiling (~74 KB/clip, so 50k ≈ 3.7 GB).
# Master switch for the whole audio feature. Downloading, normalizing (ffmpeg),
# caching and pruning clips is non-trivial background work + disk, so it's
# opt-in: off by default, no audio work happens and no play buttons render until
# the user enables it in the options flow.
CONF_AUDIO_ENABLED = "audio_enabled"
DEFAULT_AUDIO_ENABLED = False

HEADLINE_AUDIO_DAYS = 30
CONF_AUDIO_CACHE_DAYS = "audio_cache_days"
DEFAULT_AUDIO_CACHE_DAYS = 0
MAX_AUDIO_CLIPS = 50000

# Detection clips are often very quiet (faint/distant calls peak around -35 dB,
# some near -54 dB), so without normalization many are inaudible. Peak-normalize
# each cached clip to the configured target (CONF_AUDIO_NORM_TARGET, default
# DEFAULT_AUDIO_NORM_TARGET dBFS) — a *per-file* gain (loud clips aren't blown
# out), with the boost capped at AUDIO_NORM_MAX_GAIN_DB so a near-silent clip
# isn't amplified into full-scale noise. The target is user-tunable (-24..0 dB)
# to suit different dashboard hardware/output setups. The source carries audible
# base noise (the official Haikubox app surfaces it too), so this just makes the
# call audible at a consistent level. Done with ffmpeg (bundled with HA);
# silently skipped if ffmpeg is unavailable. Idempotent (re-normalizing an
# already-normalized clip computes ~0 gain and is skipped).
CONF_AUDIO_NORM_TARGET = "audio_norm_target"
DEFAULT_AUDIO_NORM_TARGET = -3
AUDIO_NORM_MAX_GAIN_DB = 50.0

# A clip whose raw peak is below this has no real signal (e.g. a silent
# soundscape ≈ -68 dB; the faintest *real* call we see is ≈ -54 dB). Rather than
# show a play button that produces inaudible output, we treat such a clip as
# missing: drop it and expose no audio_url (so no button renders).
AUDIO_SILENCE_FLOOR_DB = -60.0
