"""Lab-table reads and writes. Every function takes an open connection; callers commit."""

from __future__ import annotations

from datetime import date
from typing import Any

from psycopg.types.json import Jsonb

from tri_core.db.repo import Conn
from tri_wellness.labs.models import (
    Bound,
    Finding,
    LabResult,
    PanelContext,
    PanelSummary,
    PreviousValue,
    RawResult,
    SourceKind,
    StoredPanel,
    StoredReport,
    StoredResult,
)
from tri_wellness.labs.normalize import parse_value


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _bound_of(raw_value: str) -> Bound | None:
    """The bound `parse_value` reads off a raw printed value, for a row stored before migration
    006 added the `bound` column (left NULL, with no backfill)."""
    parsed = parse_value(raw_value)
    return parsed[1] if parsed else None


def insert_panel(
    conn: Conn,
    *,
    drawn_on: date,
    lab_name: str | None,
    source_file: str | None,
    source_kind: SourceKind,
    context: PanelContext,
    raw_extract: list[RawResult],
    results: list[LabResult],
    source_sha: str | None = None,
) -> int:
    """Insert the panel and its result rows. Runs inside the caller's transaction, so a
    failing result row leaves no panel behind."""
    row = conn.execute(
        """
        insert into lab_panels (drawn_on, lab_name, source_file, source_kind, context,
            raw_extract, source_sha)
        values (%s, %s, %s, %s, %s, %s, %s) returning id
        """,
        (
            drawn_on,
            lab_name,
            source_file,
            source_kind,
            Jsonb(context.model_dump(mode="json")),
            Jsonb([r.model_dump(mode="json") for r in raw_extract]),
            source_sha,
        ),
    ).fetchone()
    assert row is not None
    panel_id = int(row["id"])
    with conn.cursor() as cur:
        for r in results:
            cur.execute(
                """
                insert into lab_results (panel_id, marker, value, unit, raw_name, raw_value,
                    raw_unit, lab_ref_low, lab_ref_high, flag, bound)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    panel_id,
                    r.marker,
                    r.value,
                    r.unit,
                    r.raw.name,
                    r.raw.value,
                    r.raw.unit,
                    r.lab_ref_low,
                    r.lab_ref_high,
                    r.raw.flag,
                    r.bound,
                ),
            )
    return panel_id


def _panel(row: dict[str, Any]) -> StoredPanel:
    return StoredPanel(
        id=row["id"],
        drawn_on=row["drawn_on"],
        lab_name=row["lab_name"],
        source_file=row["source_file"],
        source_kind=row["source_kind"],
        context=PanelContext.model_validate(row["context"]),
        raw_extract=[RawResult.model_validate(r) for r in row["raw_extract"]],
        created_at=row["created_at"],
        source_sha=row["source_sha"],
    )


def get_panel(conn: Conn, panel_id: int) -> StoredPanel | None:
    row = conn.execute("select * from lab_panels where id = %s", (panel_id,)).fetchone()
    return _panel(row) if row else None


def latest_panel_id(conn: Conn) -> int | None:
    row = conn.execute(
        "select id from lab_panels order by drawn_on desc, id desc limit 1"
    ).fetchone()
    return int(row["id"]) if row else None


def list_panels(conn: Conn) -> list[PanelSummary]:
    rows = conn.execute(
        """
        select p.id, p.drawn_on, p.lab_name,
               jsonb_array_length(p.raw_extract) as raw_count,
               (select count(*) from lab_results r where r.panel_id = p.id) as result_count,
               exists (select 1 from lab_reports x where x.panel_id = p.id) as has_report
        from lab_panels p
        order by p.drawn_on desc, p.id desc
        """
    ).fetchall()
    return [
        PanelSummary(
            id=r["id"],
            drawn_on=r["drawn_on"],
            lab_name=r["lab_name"],
            result_count=int(r["result_count"]),
            unmapped_count=int(r["raw_count"]) - int(r["result_count"]),
            has_report=bool(r["has_report"]),
        )
        for r in rows
    ]


def panel_id_for_sha(conn: Conn, sha: str) -> int | None:
    """The panel already stored from a file with these bytes, if any (lowest id)."""
    row = conn.execute(
        "select id from lab_panels where source_sha = %s order by id limit 1", (sha,)
    ).fetchone()
    return int(row["id"]) if row else None


def find_duplicate_panels(conn: Conn, drawn_on: date, lab_name: str | None) -> list[int]:
    rows = conn.execute(
        "select id from lab_panels where drawn_on = %s and lab_name is not distinct from %s "
        "order by id",
        (drawn_on, lab_name),
    ).fetchall()
    return [int(r["id"]) for r in rows]


def _result(row: dict[str, Any]) -> StoredResult:
    return StoredResult(
        panel_id=row["panel_id"],
        marker=row["marker"],
        value=float(row["value"]),
        unit=row["unit"],
        raw_name=row["raw_name"],
        raw_value=row["raw_value"],
        raw_unit=row["raw_unit"],
        lab_ref_low=_f(row["lab_ref_low"]),
        lab_ref_high=_f(row["lab_ref_high"]),
        flag=row["flag"],
        bound=row["bound"] or _bound_of(row["raw_value"]),
    )


def list_results(conn: Conn, panel_id: int) -> list[StoredResult]:
    rows = conn.execute(
        "select * from lab_results where panel_id = %s order by marker", (panel_id,)
    ).fetchall()
    return [_result(r) for r in rows]


def lab_results_for_panel(conn: Conn, panel_id: int) -> list[LabResult]:
    """Stored rows as LabResults for evaluate. `raw` is rebuilt from the raw_* columns."""
    out: list[LabResult] = []
    for s in list_results(conn, panel_id):
        out.append(
            LabResult(
                marker=s.marker,
                value=s.value,
                unit=s.unit,
                raw=RawResult(
                    name=s.raw_name,
                    value=s.raw_value,
                    unit=s.raw_unit,
                    ref_low=None if s.lab_ref_low is None else str(s.lab_ref_low),
                    ref_high=None if s.lab_ref_high is None else str(s.lab_ref_high),
                    flag=s.flag,
                ),
                bound=s.bound,
                lab_ref_low=s.lab_ref_low,
                lab_ref_high=s.lab_ref_high,
            )
        )
    return out


def previous_values(conn: Conn, panel_id: int) -> dict[str, PreviousValue]:
    """Per marker, the value and bound from the most recent panel strictly earlier than this
    one, ordered by (drawn_on, id)."""
    rows = conn.execute(
        """
        with me as (select drawn_on, id from lab_panels where id = %s)
        select distinct on (r.marker) r.marker, p.drawn_on, r.value, r.bound, r.raw_value
        from lab_results r
        join lab_panels p on p.id = r.panel_id
        cross join me
        where (p.drawn_on, p.id) < (me.drawn_on, me.id)
        order by r.marker, p.drawn_on desc, p.id desc
        """,
        (panel_id,),
    ).fetchall()
    return {
        r["marker"]: (r["drawn_on"], float(r["value"]), r["bound"] or _bound_of(r["raw_value"]))
        for r in rows
    }


def has_earlier_panel(conn: Conn, panel_id: int) -> bool:
    """True when a panel earlier by (drawn_on, id) exists."""
    row = conn.execute(
        """
        with me as (select drawn_on, id from lab_panels where id = %s)
        select exists(
            select 1 from lab_panels p
            cross join me
            where (p.drawn_on, p.id) < (me.drawn_on, me.id)
        ) as exists
        """,
        (panel_id,),
    ).fetchone()
    assert row is not None
    return bool(row["exists"])


def marker_history(conn: Conn, marker: str) -> list[tuple[int, date, float, str]]:
    rows = conn.execute(
        """
        select p.id, p.drawn_on, r.value, r.unit
        from lab_results r join lab_panels p on p.id = r.panel_id
        where r.marker = %s
        order by p.drawn_on, p.id
        """,
        (marker,),
    ).fetchall()
    return [(int(r["id"]), r["drawn_on"], float(r["value"]), r["unit"]) for r in rows]


def insert_report(
    conn: Conn, panel_id: int, ranges_version: str, findings: list[Finding], report_md: str
) -> int:
    row = conn.execute(
        """
        insert into lab_reports (panel_id, ranges_version, findings, report_md)
        values (%s, %s, %s, %s) returning id
        """,
        (
            panel_id,
            ranges_version,
            Jsonb([f.model_dump(mode="json") for f in findings]),
            report_md,
        ),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def _report(row: dict[str, Any]) -> StoredReport:
    return StoredReport(
        id=row["id"],
        panel_id=row["panel_id"],
        ranges_version=row["ranges_version"],
        findings=[Finding.model_validate(f) for f in row["findings"]],
        report_md=row["report_md"],
        created_at=row["created_at"],
    )


def get_report(conn: Conn, report_id: int) -> StoredReport | None:
    row = conn.execute("select * from lab_reports where id = %s", (report_id,)).fetchone()
    return _report(row) if row else None


def latest_report_for_panel(conn: Conn, panel_id: int) -> StoredReport | None:
    row = conn.execute(
        "select * from lab_reports where panel_id = %s order by id desc limit 1", (panel_id,)
    ).fetchone()
    return _report(row) if row else None


def latest_report_before(conn: Conn, panel_id: int) -> StoredReport | None:
    """The newest report of the most recent earlier panel that has one (earlier by
    (drawn_on, id))."""
    row = conn.execute(
        """
        with me as (select drawn_on, id from lab_panels where id = %s)
        select x.* from lab_reports x
        join lab_panels p on p.id = x.panel_id
        cross join me
        where (p.drawn_on, p.id) < (me.drawn_on, me.id)
        order by p.drawn_on desc, p.id desc, x.id desc
        limit 1
        """,
        (panel_id,),
    ).fetchone()
    return _report(row) if row else None
