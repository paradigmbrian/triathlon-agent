"""Nutrition-table reads and writes. Every function takes an open connection; callers commit."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from psycopg.types.json import Jsonb

from tri_core.db.repo import Conn
from tri_nutrition.nutrition.models import (
    DayTarget,
    NutritionChange,
    StoredDayTarget,
    StoredFuelPlan,
)


def upsert_targets(conn: Conn, targets: list[DayTarget]) -> None:
    """Insert or replace one row per day. written_to_garmin is cleared only when kcal or a macro
    changed, so unchanged days are not re-sent."""
    with conn.cursor() as cur:
        for t in targets:
            cur.execute(
                """
                insert into nutrition_targets (day, day_type, session_kcal, total_kcal, carbs_g,
                    protein_g, fat_g, fluid_baseline_ml, goal_adjust_kcal, notes, plan_phase,
                    source, generated_at)
                values (%(day)s, %(day_type)s, %(session_kcal)s, %(total_kcal)s, %(carbs_g)s,
                    %(protein_g)s, %(fat_g)s, %(fluid_baseline_ml)s, %(goal_adjust_kcal)s,
                    %(notes)s, %(plan_phase)s, %(source)s, now())
                on conflict (day) do update set
                    day_type = excluded.day_type,
                    session_kcal = excluded.session_kcal,
                    total_kcal = excluded.total_kcal,
                    carbs_g = excluded.carbs_g,
                    protein_g = excluded.protein_g,
                    fat_g = excluded.fat_g,
                    fluid_baseline_ml = excluded.fluid_baseline_ml,
                    goal_adjust_kcal = excluded.goal_adjust_kcal,
                    notes = excluded.notes,
                    plan_phase = excluded.plan_phase,
                    source = excluded.source,
                    written_to_garmin = nutrition_targets.written_to_garmin
                        and nutrition_targets.total_kcal = excluded.total_kcal
                        and nutrition_targets.carbs_g = excluded.carbs_g
                        and nutrition_targets.protein_g = excluded.protein_g
                        and nutrition_targets.fat_g = excluded.fat_g,
                    generated_at = now()
                """,
                {**t.model_dump(mode="json"), "day": t.day, "notes": Jsonb(t.notes)},
            )


def _target(row: dict[str, Any]) -> StoredDayTarget:
    return StoredDayTarget(
        target=DayTarget(
            day=row["day"],
            day_type=row["day_type"],
            session_kcal=row["session_kcal"],
            total_kcal=row["total_kcal"],
            carbs_g=row["carbs_g"],
            protein_g=row["protein_g"],
            fat_g=row["fat_g"],
            fluid_baseline_ml=row["fluid_baseline_ml"],
            goal_adjust_kcal=row["goal_adjust_kcal"],
            plan_phase=row["plan_phase"],
            source=row["source"],
            notes=row["notes"] or [],
        ),
        written_to_garmin=row["written_to_garmin"],
    )


def list_targets(conn: Conn, start: date, end: date) -> list[StoredDayTarget]:
    rows = conn.execute(
        "select * from nutrition_targets where day between %s and %s order by day", (start, end)
    ).fetchall()
    return [_target(r) for r in rows]


def mark_targets_written(conn: Conn, days: list[date]) -> None:
    if not days:
        return
    conn.execute(
        "update nutrition_targets set written_to_garmin = true where day = any(%s)", (days,)
    )


def delete_unwritten_targets(conn: Conn) -> int:
    return conn.execute("delete from nutrition_targets where not written_to_garmin").rowcount


def upsert_fuel_plan(
    conn: Conn,
    kind: str,
    day: date,
    tp_workout_id: str | None,
    payload: dict[str, Any],
    violations: list[str],
) -> int:
    row = conn.execute(
        """
        insert into fuel_plans (kind, day, tp_workout_id, payload, violations, generated_at)
        values (%s, %s, %s, %s, %s, now())
        on conflict (kind, day, coalesce(tp_workout_id, '')) do update set
            payload = excluded.payload,
            violations = excluded.violations,
            written = false,
            generated_at = now()
        returning id
        """,
        (kind, day, tp_workout_id, Jsonb(payload), Jsonb(violations)),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def _fuel(row: dict[str, Any]) -> StoredFuelPlan:
    return StoredFuelPlan(
        id=row["id"],
        kind=row["kind"],
        day=row["day"],
        tp_workout_id=row["tp_workout_id"],
        tp_note_id=row["tp_note_id"],
        payload=row["payload"],
        violations=row["violations"] or [],
        written=row["written"],
    )


def list_fuel_plans(conn: Conn, start: date, end: date) -> list[StoredFuelPlan]:
    rows = conn.execute(
        "select * from fuel_plans where day between %s and %s order by day, kind, id",
        (start, end),
    ).fetchall()
    return [_fuel(r) for r in rows]


def mark_fuel_written(conn: Conn, plan_id: int, tp_note_id: str | None) -> None:
    conn.execute(
        "update fuel_plans set written = true, tp_note_id = coalesce(%s::text, tp_note_id) "
        "where id = %s",
        (tp_note_id, plan_id),
    )


def delete_unwritten_fuel_plans(conn: Conn) -> int:
    return conn.execute("delete from fuel_plans where not written").rowcount


def insert_change(
    conn: Conn, thread_id: str, change: NutritionChange, result: dict[str, Any] | None
) -> int:
    row = conn.execute(
        """
        insert into nutrition_changes (thread_id, operation, target_key, payload, result, reason)
        values (%s, %s, %s, %s, %s, %s) returning id
        """,
        (
            thread_id,
            change.op,
            change.target_key,
            Jsonb(change.model_dump(mode="json")),
            Jsonb(result) if result is not None else None,
            change.reason,
        ),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def owned_note_ids(conn: Conn) -> set[str]:
    rows = conn.execute(
        "select distinct target_key from nutrition_changes "
        "where operation = 'set_race_note' and target_key <> ''"
    ).fetchall()
    return {r["target_key"] for r in rows}


def last_change_at(conn: Conn) -> datetime | None:
    row = conn.execute("select max(applied_at) as at from nutrition_changes").fetchone()
    return row["at"] if row else None
