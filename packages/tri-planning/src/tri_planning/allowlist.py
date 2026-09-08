"""Which MCP tools each part of the planning agent may call.

Write tools are never bound to a sub-agent; only the apply node calls them, by name, through
ToolCaller.call_json.
"""

TP_WRITE_TOOLS = [
    "tp_create_workout",
    "tp_update_workout",
    "tp_delete_workout",
    "tp_create_event",
    "tp_apply_training_plan",
]
TP_READ_TOOLS = ["tp_get_workouts", "tp_list_training_plans"]
GARMIN_LIVE_TOOLS = ["get_training_readiness", "get_hrv_data"]
