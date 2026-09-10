"""Which Garmin tools the nutrition agent's server process registers and which each node may use.

Write tools are never bound to a sub-agent; only the apply node calls them, by name, through
ToolCaller.call_json.
"""

GARMIN_INTAKE_TOOLS = ["get_user_profile", "get_body_composition", "get_nutrition_daily_settings"]
GARMIN_CHECKIN_TOOLS = [
    "get_body_composition",
    "get_nutrition_daily_food_log",
    "get_nutrition_daily_meals",
    "get_hydration_data",
]
GARMIN_WRITE_TOOLS = ["set_nutrition_daily_settings"]
GARMIN_SERVER_TOOLS = sorted(set(GARMIN_INTAKE_TOOLS + GARMIN_CHECKIN_TOOLS + GARMIN_WRITE_TOOLS))
