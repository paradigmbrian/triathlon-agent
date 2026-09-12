"""Which MCP tools the coach's two sessions bind: the union of every sub-agent's lists, so one
Garmin process and one TrainingPeaks process serve the analyst, planning and nutrition.

Write tools are bound only so the packages' `apply_changes` can reach them through a
ToolsCaller; they are never handed to a model."""

from tri_analyze import allowlist as analyze
from tri_nutrition import allowlist as nutrition
from tri_planning import allowlist as planning

GARMIN_TOOLS: list[str] = sorted(
    set(analyze.GARMIN_LIVE_TOOLS)
    | set(planning.GARMIN_LIVE_TOOLS)
    | set(nutrition.GARMIN_SERVER_TOOLS)
)
TP_TOOLS: list[str] = sorted(
    set(analyze.TP_LIVE_TOOLS)
    | set(planning.TP_READ_TOOLS)
    | set(planning.TP_WRITE_TOOLS)
    | set(nutrition.TP_READ_TOOLS)
    | set(nutrition.TP_WRITE_TOOLS)
)

# What the analyst (an agent-as-tool inside the coach) may call live: read-only, its own lists.
ANALYST_GARMIN_TOOLS: list[str] = list(analyze.GARMIN_LIVE_TOOLS)
ANALYST_TP_TOOLS: list[str] = list(analyze.TP_LIVE_TOOLS)
