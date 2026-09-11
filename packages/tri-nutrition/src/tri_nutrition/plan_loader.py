"""The horizon's planned sessions and their context, read from planning's tables and workouts.

The only SQL over training_goals, training_plans and plan_weeks in this package. Planning owns
those tables; this module only reads them.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from tri_core.db.repo import Conn
from tri_nutrition.nutrition.models import Intensity, PlanContext, Session, Source

SPORTS = {"swim", "bike", "run", "brick", "strength"}


def intensity_from_if(planned_if: float | None) -> Intensity:
    if planned_if is None or planned_if < 0.75:
        return "endurance"
    if planned_if < 0.85:
        return "tempo"
    if planned_if < 0.95:
        return "threshold"
    return "vo2"


def session_from_workout(row: dict[str, Any]) -> Session | None:
    sport = row.get("sport")
    secs = row.get("planned_duration_sec")
    if sport not in SPORTS or not secs:
        return None
    dist = row.get("planned_distance_m")
    return Session(
        day=row["workout_date"],
        sport=sport,
        duration_min=int(secs) // 60,
        intensity=intensity_from_if(float(row["planned_if"]) if row.get("planned_if") else None),
        tp_workout_id=str(row["tp_workout_id"]),
        title=row.get("title") or "",
        planned_tss=float(row["planned_tss"]) if row.get("planned_tss") is not None else None,
        distance_km=float(dist) / 1000 if dist else None,
    )


def sessions_from_designed(designed: dict[str, Any], start: date, end: date) -> list[Session]:
    """Sessions of one designed week (planning's PlannedWeek JSON) that fall in [start, end]."""
    out: list[Session] = []
    for s in designed.get("sessions", []):
        day = date.fromisoformat(str(s["date"])[:10])
        if not start <= day <= end or s.get("sport") not in SPORTS:
            continue
        out.append(
            Session(
                day=day,
                sport=s["sport"],
                duration_min=int(s.get("duration_minutes") or 0),
                intensity=s.get("intensity") or "endurance",
                title=s.get("title") or "",
                planned_tss=float(s["tss_planned"]) if s.get("tss_planned") is not None else None,
            )
        )
    return out


def attach_workout_ids(sessions: list[Session], rows: list[dict[str, Any]]) -> list[Session]:
    """Give plan-designed sessions the id of the synced TrainingPeaks workout on the same day
    and sport (title breaks ties). Sessions that already carry an id keep it."""
    used: set[str] = set()
    out: list[Session] = []
    for s in sessions:
        if s.tp_workout_id is not None:
            used.add(s.tp_workout_id)
            out.append(s)
            continue
        candidates = [
            r
            for r in rows
            if r["workout_date"] == s.day
            and r["sport"] == s.sport
            and str(r["tp_workout_id"]) not in used
        ]
        exact = [r for r in candidates if (r.get("title") or "") == s.title]
        pool = exact or candidates
        if not pool:
            out.append(s)
            continue
        wid = str(pool[0]["tp_workout_id"])
        used.add(wid)
        out.append(s.model_copy(update={"tp_workout_id": wid}))
    return out


def _workouts_between(conn: Conn, start: date, end: date) -> list[dict[str, Any]]:
    return conn.execute(
        "select tp_workout_id, workout_date, sport, title from workouts "
        "where workout_date between %s and %s order by workout_date, tp_workout_id",
        (start, end),
    ).fetchall()


def _active_goal(conn: Conn) -> dict[str, Any] | None:
    return conn.execute(
        "select id, goal_type, event_name, event_date, priority, weekly_hours_max "
        "from training_goals "
        "where status = 'active' order by created_at desc, id desc limit 1"
    ).fetchone()


def _active_plan_weeks(conn: Conn, goal_id: int) -> list[dict[str, Any]]:
    return conn.execute(
        "select w.week_start, w.phase, w.designed from plan_weeks w "
        "join training_plans p on p.id = w.plan_id "
        "where p.goal_id = %s and p.status = 'active' order by w.week_start",
        (goal_id,),
    ).fetchall()


def _planned_workouts(conn: Conn, start: date, end: date) -> list[dict[str, Any]]:
    return conn.execute(
        "select tp_workout_id, workout_date, sport, title, planned_duration_sec, "
        "planned_distance_m, planned_tss, planned_if from workouts "
        "where not completed and workout_date between %s and %s order by workout_date",
        (start, end),
    ).fetchall()


def _ftp(conn: Conn) -> int | None:
    row = conn.execute("select ftp_watts from athlete_profile where id = 1").fetchone()
    return int(row["ftp_watts"]) if row and row["ftp_watts"] is not None else None


def load_horizon(conn: Conn, today: date, horizon_days: int) -> tuple[list[Session], PlanContext]:
    end = today + timedelta(days=horizon_days - 1)
    goal = _active_goal(conn)
    phases: dict[date, Any] = {}
    sessions: list[Session] = []
    source: Source = "profile_hours"
    if goal is not None:
        weeks = _active_plan_weeks(conn, int(goal["id"]))
        phases = {w["week_start"]: w["phase"] for w in weeks}
        for w in weeks:
            if w["designed"]:
                sessions += sessions_from_designed(w["designed"], today, end)
        if sessions:
            source = "plan"
            sessions = attach_workout_ids(sessions, _workouts_between(conn, today, end))
    if not sessions:
        for row in _planned_workouts(conn, today, end):
            s = session_from_workout(row)
            if s is not None:
                sessions.append(s)
        if sessions:
            source = "tp_calendar"
    weekly_hours = (
        float(goal["weekly_hours_max"])
        if goal is not None and goal.get("weekly_hours_max") is not None
        else None
    )
    ctx = PlanContext(
        source=source,
        ftp_watts=_ftp(conn),
        event_date=goal["event_date"] if goal is not None else None,
        event_priority=goal["priority"] if goal is not None else None,
        event_name=goal["event_name"] if goal is not None else None,
        goal_type=goal["goal_type"] if goal is not None else None,
        phases=phases,
        weekly_hours=weekly_hours if source == "profile_hours" else None,
    )
    return sorted(sessions, key=lambda s: (s.day, s.sport)), ctx


def describe(sessions: list[Session], ctx: PlanContext) -> dict[str, Any]:
    """JSON-safe summary for the read_training_plan tool."""
    return {
        "source": ctx.source,
        "event_date": ctx.event_date.isoformat() if ctx.event_date else None,
        "event_priority": ctx.event_priority,
        "event_name": ctx.event_name,
        "goal_type": ctx.goal_type,
        "ftp_watts": ctx.ftp_watts,
        "weekly_hours": ctx.weekly_hours,
        "phases": {d.isoformat(): p for d, p in sorted(ctx.phases.items())},
        "sessions": [
            {
                "day": s.day.isoformat(),
                "sport": s.sport,
                "minutes": s.duration_min,
                "intensity": s.intensity,
                "tss": s.planned_tss,
                "title": s.title,
            }
            for s in sessions
        ],
    }
