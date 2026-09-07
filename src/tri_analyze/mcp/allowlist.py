"""Which MCP tools the agent may call live. Everything else stays behind the sync."""

GARMIN_LIVE_TOOLS = [
    "get_activity",
    "get_activity_splits",
    "get_training_readiness",
    "get_hrv_data",
]
TP_LIVE_TOOLS = ["tp_get_workout"]
