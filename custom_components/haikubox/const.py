DOMAIN = "haikubox"

CONF_SERIAL = "serial"
CONF_DEVICE_NAME = "device_name"

API_BASE = "https://api.haikubox.com"
IMAGES_BASE = "https://haikubox-images.s3.amazonaws.com"

# How often to poll the API (seconds)
DEFAULT_SCAN_INTERVAL = 600  # 10 minutes

# Sliding window for the recent_detections sensor + the sticky / new-species
# / 7-day-store pipelines. The integration makes exactly one /detections call
# per poll (hours=DAILY_WINDOW_HOURS) and filters that response client-side by
# this many hours for the recent view — the 1-hour window was previously a
# separate API request, but every consumer of it can be derived from the 24h
# response with a timestamp filter.
RECENT_WINDOW_HOURS = 1

# Rolling window for the "daily" sensors. The Haikubox /daily-count
# endpoint is a server-side calendar day; instead we derive a true
# trailing 24-hour view from /detections (24 is the endpoint's max).
# This is also the only window we actually fetch — see RECENT_WINDOW_HOURS.
DAILY_WINDOW_HOURS = 24

# Cap on the per-event `detections` list exposed on the last_detection
# sensor — the N most recent individual events from the 24h payload,
# distinct from recent_detections (which is one record per species). The
# 24h payload is the natural ceiling; this is a soft cap for attribute
# size (~50 × ~250 B ≈ 12 KB, around HA's state-attribute size warning).
LAST_DETECTION_EVENT_LIMIT = 50

# Cap on the lifetime-history `detections` list exposed on the new_species
# sensor — the N most recently first-seen species from the seen_species
# log, sorted by first_seen desc. Sticky like last_detection's per-event
# list, but per-species (one record per first-seen species, not per event).
# Same soft attribute-size rationale as LAST_DETECTION_EVENT_LIMIT.
NEW_SPECIES_HISTORY_LIMIT = 50

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
TRIGGER_TYPES = (TRIGGER_NEW_SPECIES, TRIGGER_UNUSUAL_VISITOR)

# unusual_visitor fires when a known species reappears after at least this
# many days unheard. Built on the persisted last-seen gap, so it's immune to
# the calendar-year reset that makes raw yearly rarity unreliable as an alert
# (the reason `notable` blends in recency in the first place). Configurable
# via the options flow.
CONF_ABSENCE_DAYS = "absence_days"
DEFAULT_ABSENCE_DAYS = 30
