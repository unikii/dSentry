"""Shared limits used by request models and route handlers.

Keeping these in one module prevents the route constants and the Pydantic
`max_length` annotations from drifting apart.
"""

MAX_DEVICES_PER_PUSH = 500
MAX_METRICS_PER_PUSH = 5000
MAX_EVENTS_PER_PUSH = 500
MAX_METAS_PER_PUSH = 500

# Compressed node payloads are capped at 15 KiB (the node sends brotli).
# Base64 inflates by ~4/3; request models use that upper bound.
MAX_RAW_COMPRESSED_SIZE = 15 * 1024
MAX_RAW_BASE64_CHARS = ((MAX_RAW_COMPRESSED_SIZE + 2) // 3) * 4

MAX_ENABLED_ALERTS = 2

MAX_TAGS = 50
MAX_TAG_LENGTH = 50

# Upper bound for raw metric exports (custom start/end range). Prevents one
# request from asking VictoriaMetrics for years of samples across every field.
MAX_METRIC_EXPORT_DAYS = 90
MAX_METRIC_EXPORT_POINTS = 100_000

# Only these event types leave an unacknowledged marker on the device. A
# recovery/online event must not make a healthy disk look critical.
UNHANDLED_EVENT_TYPES = {
    "device_smart_fail",
    "device_threshold_warning",
    "device_threshold_critical",
    "device_missing",
}
