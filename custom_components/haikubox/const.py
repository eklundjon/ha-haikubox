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
