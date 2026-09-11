"""The fixed message a scheduled check-in sends to the adjust sub-agent."""

CHECKIN_PROMPT = """\
Scheduled check-in. Review the last 7 days against the plan; flag sessions with RPE >= 8 or
feeling <= 3; compare 3-day readiness and HRV to the 30-day baseline; note TSB entering this
week; if the window extension is needed, call design_next_week. Then either propose the calendar
changes you would make (propose_calendar_changes) or say clearly that no changes are needed."""
