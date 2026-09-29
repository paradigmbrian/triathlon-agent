"""compute_progress: weeks, the PMC, ramp windows, range clipping and sport sums, over plain dict
rows (no database)."""

from datetime import date, timedelta
from decimal import Decimal

from tri_web.progress import compute_progress, metrics_floor, range_floor

TODAY = date(2026, 9, 16)  # a Wednesday


def w(day: date, sport: str = "run", *, completed: bool = True, **cols):
    return {"workout_date": day, "sport": sport, "completed": completed, **cols}


def m(day: date, ctl=None, atl=None, tsb=None, tss_day=None):
    return {"metric_date": day, "ctl": ctl, "atl": atl, "tsb": tsb, "tss_day": tss_day}


def test_weeks_split_on_monday_and_the_current_week_is_partial():
    rows = [
        w(date(2026, 9, 13), actual_duration_sec=3600),  # Sunday
        w(date(2026, 9, 14), actual_duration_sec=1800),  # Monday
    ]
    out = compute_progress("6w", TODAY, rows, [])
    by_start = {x.week_start: x for x in out.weeks}
    assert by_start[date(2026, 9, 7)].by_sport["run"].duration_sec == 3600
    assert by_start[date(2026, 9, 14)].by_sport["run"].duration_sec == 1800
    assert [x.partial for x in out.weeks] == [False] * 6 + [True]


def test_range_starts_on_a_monday_and_clips_older_rows():
    assert range_floor("6w", TODAY) == date(2026, 8, 3)
    assert metrics_floor("6w", TODAY) == TODAY - timedelta(days=365)
    rows = [
        w(date(2026, 8, 2), actual_duration_sec=999),
        w(date(2026, 8, 3), actual_duration_sec=60),
    ]
    out = compute_progress("6w", TODAY, rows, [])
    assert out.start == date(2026, 8, 3)
    assert out.weeks[0].week_start == date(2026, 8, 3)
    assert out.weeks[0].by_sport["run"].duration_sec == 60
    assert out.share.completed.duration_sec == {"run": 60}


def test_all_starts_at_the_earliest_data_monday():
    out = compute_progress(
        "all", TODAY, [w(date(2025, 3, 5), actual_tss=40)], [m(date(2025, 6, 1), ctl=10)]
    )
    assert out.start == date(2025, 3, 3)
    assert len(out.pmc) == (TODAY - date(2025, 3, 3)).days + 1


def test_pmc_keeps_a_gap_as_null_and_never_interpolates():
    out = compute_progress(
        "6w",
        TODAY,
        [],
        [
            m(date(2026, 9, 14), ctl=40, atl=44, tsb=-4, tss_day=60),
            m(date(2026, 9, 16), ctl=Decimal("41.5"), atl=45, tsb=-3.5),
        ],
    )
    by = {p.date: p for p in out.pmc}
    assert by[date(2026, 9, 15)].ctl is None and by[date(2026, 9, 15)].tsb is None
    assert by[date(2026, 9, 16)].ctl == 41.5
    assert out.as_of == date(2026, 9, 16)
    assert len(out.pmc) == 45  # 2026-08-03 through today


def test_ramp_windows_and_a_missing_start_gives_no_delta():
    metrics = [m(date(2026, 9, 16), ctl=40.0), m(date(2026, 9, 9), ctl=38.5)]
    out = compute_progress("6w", TODAY, [], metrics)
    r = {x.days: x for x in out.ramp}
    assert r[7].delta == 1.5
    assert len(r[7].series) == 8 and r[7].series[0] == 38.5 and r[7].series[-1] == 40.0
    assert r[28].delta is None and len(r[28].series) == 29
    assert sorted(r) == [7, 28, 90, 365]


def test_ramp_reaches_past_the_range_for_the_long_windows():
    metrics = [m(date(2026, 9, 16), ctl=40.0), m(TODAY - timedelta(days=90), ctl=30.0)]
    out = compute_progress("6w", TODAY, [], metrics)
    assert {x.days: x.delta for x in out.ramp}[90] == 10.0


def test_sums_treat_null_columns_as_zero_and_null_never_wins_longest():
    rows = [
        w(
            date(2026, 9, 14),
            "bike",
            actual_duration_sec=3600,
            actual_distance_m=None,
            elevation_gain_m=None,
            calories=None,
            actual_tss=None,
        ),
        w(
            date(2026, 9, 15),
            "bike",
            actual_duration_sec=None,
            actual_distance_m=5000,
            elevation_gain_m=120,
            calories=300,
            actual_tss=50,
        ),
    ]
    week = compute_progress("6w", TODAY, rows, []).weeks[-1]
    bike = week.by_sport["bike"]
    assert (bike.duration_sec, bike.distance_m, bike.elevation_m, bike.calories, bike.tss) == (
        3600,
        5000,
        120,
        300,
        50,
    )
    assert week.longest.duration_sec == 3600 and week.longest.distance_m == 5000


def test_a_week_with_no_workouts_is_zeroed_not_missing():
    week = compute_progress("6w", TODAY, [], []).weeks[0]
    assert week.by_sport == {} and week.longest.duration_sec == 0 and week.longest.distance_m == 0


def test_share_uses_actuals_for_completed_and_planned_columns_for_everything():
    rows = [
        w(
            date(2026, 9, 14),
            "swim",
            actual_duration_sec=1800,
            actual_distance_m=1500,
            planned_duration_sec=2400,
            planned_distance_m=2000,
        ),
        w(
            date(2026, 9, 15),
            "run",
            completed=False,
            planned_duration_sec=3600,
            planned_distance_m=10000,
            actual_duration_sec=77,
        ),
    ]
    share = compute_progress("6w", TODAY, rows, []).share
    assert share.completed.duration_sec == {"swim": 1800}
    assert share.completed.distance_m == {"swim": 1500}
    assert share.planned.duration_sec == {"swim": 2400, "run": 3600}
    assert share.planned.distance_m == {"swim": 2000, "run": 10000}


def test_rows_after_today_are_ignored():
    out = compute_progress(
        "6w",
        TODAY,
        [w(date(2026, 9, 20), actual_duration_sec=60)],
        [m(date(2026, 9, 20), ctl=99)],
    )
    assert out.as_of is None and out.weeks[-1].by_sport == {}


def test_an_empty_store_is_all_empty_and_never_raises():
    out = compute_progress("12m", TODAY, [], [])
    assert out.as_of is None
    assert all(p.ctl is None for p in out.pmc)
    assert all(x.delta is None for x in out.ramp)
    assert out.share.completed.duration_sec == {} and out.share.planned.distance_m == {}


def test_metrics_floor_reaches_a_year_before_the_latest_ctl_day_not_before_today():
    lag = TODAY - timedelta(days=2)
    assert metrics_floor("6w", TODAY, as_of=lag) == lag - timedelta(days=365)
    assert metrics_floor("6w", TODAY) == TODAY - timedelta(days=365)
