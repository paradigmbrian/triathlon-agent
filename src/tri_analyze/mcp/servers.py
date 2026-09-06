"""Launch specifications for the two MCP servers."""

from dataclasses import dataclass, field

from tri_analyze.config import Settings

GARMIN_REPO = "https://github.com/Taxuspt/garmin_mcp"
TP_REPO = "https://github.com/JamsusMaximus/trainingpeaks-mcp"

# Only these Garmin tools get registered by the server (keeps the tool list small).
GARMIN_ENABLED_TOOLS = [
    "get_stats",
    "get_sleep_summary_range",
    "get_hrv_data",
    "get_training_readiness",
    "get_activities_by_date",
    "get_activity",
    "get_activity_splits",
]


@dataclass
class ServerSpec:
    name: str
    command: str
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)


def garmin_spec(settings: Settings) -> ServerSpec:
    env = {
        "GARMIN_ENABLED_TOOLS": ",".join(GARMIN_ENABLED_TOOLS),
        "GARMIN_MCP_CALL_TIMEOUT": "90",
    }
    if settings.garmin_email:
        env["GARMIN_EMAIL"] = settings.garmin_email
    if settings.garmin_password:
        env["GARMIN_PASSWORD"] = settings.garmin_password
    return ServerSpec(
        name="garmin",
        command="uvx",
        args=[
            "--python",
            "3.12",
            "--from",
            f"git+{GARMIN_REPO}@{settings.garmin_mcp_ref}",
            "garmin-mcp",
        ],
        env=env,
    )


def trainingpeaks_spec(settings: Settings) -> ServerSpec:
    env: dict[str, str] = {}
    if settings.tp_auth_cookie:
        env["TP_AUTH_COOKIE"] = settings.tp_auth_cookie
    return ServerSpec(
        name="trainingpeaks",
        command="uvx",
        args=["--from", f"git+{TP_REPO}@{settings.tp_mcp_ref}", "tp-mcp", "serve"],
        env=env,
    )
