from datetime import date, time

import pytest

from tri_wellness import repo
from tri_wellness.labs.models import Finding, LabResult, PanelContext, RawResult

pytestmark = pytest.mark.db

D1, D2, D3 = date(2031, 1, 15), date(2031, 4, 15), date(2031, 7, 15)
CTX = PanelContext(fasting=True, draw_time=time(7, 30), supplements=["vitamin d"], symptoms=[])


def raw(name, value, unit="ng/mL", ref_low=None, ref_high=None, flag=None):
    return RawResult(
        name=name, value=value, unit=unit, ref_low=ref_low, ref_high=ref_high, flag=flag
    )


def lr(marker, value, unit="ng/mL", name=None, **over) -> LabResult:
    base = dict(
        marker=marker,
        value=value,
        unit=unit,
        raw=raw(name or marker, str(value), unit, "30", "400", "L" if value < 30 else None),
        lab_ref_low=30.0,
        lab_ref_high=400.0,
    )
    base.update(over)
    return LabResult(**base)


def panel(conn, drawn_on, results, lab="Quest", extra_raw=()):
    return repo.insert_panel(
        conn,
        drawn_on=drawn_on,
        lab_name=lab,
        source_file=f"/labs/{drawn_on}.pdf",
        source_kind="pdf",
        context=CTX,
        raw_extract=[r.raw for r in results] + list(extra_raw),
        results=results,
    )


def test_insert_and_get_panel_roundtrip(wdb):
    pid = panel(
        wdb,
        D1,
        [lr("ferritin", 42.0), lr("hs_crp", 0.4, "mg/L")],
        extra_raw=[raw("ESR", "4", "mm/hr")],
    )
    p = repo.get_panel(wdb, pid)
    assert p is not None and p.id == pid
    assert (p.drawn_on, p.lab_name, p.source_kind) == (D1, "Quest", "pdf")
    assert p.source_file == f"/labs/{D1}.pdf"
    assert p.context == CTX
    assert [r.name for r in p.raw_extract] == ["ferritin", "hs_crp", "ESR"]
    assert repo.get_panel(wdb, pid + 1000) is None


def test_results_roundtrip_and_lab_results_rebuild(wdb):
    fer = lr("ferritin", 42.0, name="Ferritin, Serum", note="converted from 42 ug/L")
    crp = lr(
        "hs_crp",
        0.3,
        "mg/L",
        raw=raw("hs-CRP", "<0.3", "mg/L", None, "3.0"),
        lab_ref_low=None,
        lab_ref_high=3.0,
    )
    pid = panel(wdb, D1, [fer, crp])
    stored = repo.list_results(wdb, pid)
    assert [s.marker for s in stored] == ["ferritin", "hs_crp"]  # marker order
    f = stored[0]
    assert (f.value, f.unit, f.raw_name, f.raw_value, f.raw_unit) == (
        42.0,
        "ng/mL",
        "Ferritin, Serum",
        "42.0",
        "ng/mL",
    )
    assert (f.lab_ref_low, f.lab_ref_high, f.flag) == (30.0, 400.0, None)
    c = stored[1]
    assert (c.raw_value, c.lab_ref_low, c.lab_ref_high) == ("<0.3", None, 3.0)
    rebuilt = repo.lab_results_for_panel(wdb, pid)
    assert [(r.marker, r.value, r.unit, r.lab_ref_low, r.lab_ref_high) for r in rebuilt] == [
        ("ferritin", 42.0, "ng/mL", 30.0, 400.0),
        ("hs_crp", 0.3, "mg/L", None, 3.0),
    ]
    assert rebuilt[0].raw.name == "Ferritin, Serum" and rebuilt[1].raw.value == "<0.3"
    assert rebuilt[0].note is None  # notes are not stored; the report reads the raw columns


def test_insert_panel_is_atomic_on_duplicate_marker(wdb):
    import psycopg

    with pytest.raises(psycopg.errors.UniqueViolation), wdb.transaction():
        panel(wdb, D1, [lr("ferritin", 42.0), lr("ferritin", 43.0)])
    assert all(p.drawn_on != D1 for p in repo.list_panels(wdb))  # no panel row left behind


def test_latest_panel_and_list_panels(wdb):
    a = panel(wdb, D2, [lr("ferritin", 40.0)])
    b = panel(
        wdb, D1, [lr("ferritin", 35.0), lr("hs_crp", 0.5, "mg/L")], extra_raw=[raw("ESR", "4")]
    )
    c = panel(wdb, D2, [lr("ferritin", 41.0)], lab="LabCorp")
    assert repo.latest_panel_id(wdb) == c  # same drawn_on as a, higher id
    summaries = [s for s in repo.list_panels(wdb) if s.id in (a, b, c)]
    assert [s.id for s in summaries] == [c, a, b]
    by_id = {s.id: s for s in summaries}
    assert (by_id[b].result_count, by_id[b].unmapped_count, by_id[b].has_report) == (2, 1, False)
    assert (by_id[a].result_count, by_id[a].unmapped_count) == (1, 0)
    repo.insert_report(wdb, b, "2026-09-11.1", [], "# report")
    assert {s.id: s.has_report for s in repo.list_panels(wdb) if s.id in (a, b)} == {
        a: False,
        b: True,
    }


def test_find_duplicate_panels(wdb):
    a = panel(wdb, D1, [lr("ferritin", 40.0)])
    panel(wdb, D1, [lr("ferritin", 40.0)], lab="LabCorp")
    panel(wdb, D2, [lr("ferritin", 40.0)])
    assert repo.find_duplicate_panels(wdb, D1, "Quest") == [a]
    assert repo.find_duplicate_panels(wdb, D3, "Quest") == []
    n = panel(wdb, D3, [lr("ferritin", 40.0)], lab=None)
    assert repo.find_duplicate_panels(wdb, D3, None) == [n]


def test_previous_values_and_marker_history(wdb):
    p1 = panel(wdb, D1, [lr("ferritin", 35.0), lr("hs_crp", 0.5, "mg/L")])
    p2 = panel(wdb, D2, [lr("ferritin", 40.0)])
    p3 = panel(wdb, D3, [lr("ferritin", 48.0), lr("hs_crp", 0.9, "mg/L"), lr("tsh", 1.5, "mIU/L")])
    assert repo.previous_values(wdb, p1) == {}
    assert repo.previous_values(wdb, p2) == {"ferritin": (D1, 35.0), "hs_crp": (D1, 0.5)}
    assert repo.previous_values(wdb, p3) == {"ferritin": (D2, 40.0), "hs_crp": (D1, 0.5)}
    assert repo.marker_history(wdb, "ferritin") == [
        (p1, D1, 35.0, "ng/mL"),
        (p2, D2, 40.0, "ng/mL"),
        (p3, D3, 48.0, "ng/mL"),
    ]
    assert repo.marker_history(wdb, "tsh") == [(p3, D3, 1.5, "mIU/L")]
    assert repo.marker_history(wdb, "nope") == []


def test_previous_values_same_day_uses_lower_id(wdb):
    p1 = panel(wdb, D1, [lr("ferritin", 35.0)])
    p2 = panel(wdb, D1, [lr("ferritin", 36.0)], lab="LabCorp")
    assert repo.previous_values(wdb, p2) == {"ferritin": (D1, 35.0)}
    assert repo.previous_values(wdb, p1) == {}


def test_reports_roundtrip(wdb):
    pid = panel(wdb, D1, [lr("ferritin", 42.0)])
    finding = Finding(
        marker="ferritin",
        display="Ferritin",
        system="iron",
        value=42.0,
        unit="ng/mL",
        conventional_status="in_range",
        functional_status="suboptimal_low",
        functional_range=(50.0, 150.0),
        previous=(date(2030, 10, 1), 35.0),
        delta_pct=20.0,
        active_confounders=["recent_hard_session"],
        athlete_note="note",
    )
    assert repo.latest_report_for_panel(wdb, pid) is None
    r1 = repo.insert_report(wdb, pid, "2026-09-11.1", [finding], "# first")
    r2 = repo.insert_report(wdb, pid, "2026-09-11.2", [finding], "# second")
    got = repo.get_report(wdb, r1)
    assert got is not None and got.panel_id == pid and got.ranges_version == "2026-09-11.1"
    assert got.findings == [finding] and got.report_md == "# first"
    latest = repo.latest_report_for_panel(wdb, pid)
    assert latest is not None and latest.id == r2 and latest.report_md == "# second"
    assert repo.get_report(wdb, r2 + 1000) is None
