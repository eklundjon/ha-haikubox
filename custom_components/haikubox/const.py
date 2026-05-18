DOMAIN = "haikubox"

CONF_SERIAL = "serial"
CONF_DEVICE_NAME = "device_name"

API_BASE = "https://api.haikubox.com"
IMAGES_BASE = "https://haikubox-images.s3.amazonaws.com"

# How often to poll the API (seconds)
DEFAULT_SCAN_INTERVAL = 600  # 10 minutes

# Detection window passed to the /detections endpoint (integer hours, max 24).
# Needs to be wide enough to bridge one poll interval with overlap —
# 1 hour gives a 30× buffer against a 2-minute poll interval.
DETECTION_HOURS = 1

# Rolling window for the "daily" sensors. The Haikubox /daily-count
# endpoint is a server-side calendar day; instead we derive a true
# trailing 24-hour view from /detections (24 is the endpoint's max).
DAILY_WINDOW_HOURS = 24
