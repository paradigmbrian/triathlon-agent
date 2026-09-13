from datetime import date, timedelta

import pytest

from tri_coach.context import CoachContext, load_context, render_context
from tri_coach.models import ChangeSet, Proposal
from tri_nutrition import repo as nrepo
from tri_nutrition import store as S
from tri_nutrition.nutrition.models import DayTarget, NutritionProfile
from tri_nutrition.testing import PROFILE_ARGS
from tri_planning import repo
from tri_planning.planning.models import TrainingGoal, WeekTarget
from tri_planning.testing import GOAL_ARGS, MONDAY
from tri_wellness import repo as wrepo
from tri_wellness.labs.models import Finding
from tri_wellness.testing import REPORT_OK, seed_panel

pytestmark = pytest.mark.db


def seed_plan(conn):
    gid = repo.insert_goal(conn, TrainingGoal(**GOAL_ARGS))
    targets = [
        WeekTarget(
            week_start=MONDAY + timedelta(weeks=i), phase="build", target_tss=300, target_hours=6
        )
        for i in range(3)
    ]
    pid = repo.insert_plan(conn, gid, "generated", None, targets)
    repo.mark_weeks_written(conn, pid, [MONDAY])
    return gid, pid


async def test_load_context_from_empty_database(nocommit, mem_store):
    ctx = await load_context(nocommit, mem_store, MONDAY, None)
    assert ctx.phase == "intake" and ctx.goal is None and ctx.plan is None
    assert ctx.profile is None and ctx.targets_through is None and ctx.pending is None
    text = render_context(ctx)
    assert "Today is 2026-09-14" in text
    assert "Training plan: none (phase intake)" in text
    assert "Nutrition: no profile" in text


async def test_load_context_with_plan_profile_and_targets(ndb, mem_store):
    gid, pid = seed_plan(ndb)
    await S.put_profile(mem_store, NutritionProfile(**PROFILE_ARGS))
    nrepo.upsert_targets(
        ndb,
        [
            DayTarget(
                day=MONDAY + timedelta(days=i),
                day_type="easy",
                session_kcal=0,
                total_kcal=2800,
                carbs_g=280,
                protein_g=150,
                fat_g=120,
                fluid_baseline_ml=2800,
                source="plan",
            )
            for i in range(5)
        ],
    )
    ctx = await load_context(ndb, mem_store, MONDAY + timedelta(days=2), None)
    assert ctx.phase == "active" and ctx.goal is not None and ctx.plan is not None
    assert ctx.this_week is not None and ctx.this_week.week_start == MONDAY
    assert ctx.designed_remaining == 0  # nothing designed in the seed
    assert ctx.profile is not None and ctx.targets_through == MONDAY + timedelta(days=4)
    text = render_context(ctx)
    assert "Training plan: olympic, City Tri on" in text and "phase active" in text
    assert "This week (build): target 300 TSS / 6.0 h" in text
    assert "designed weeks remaining: 0" in text
    assert "Nutrition: goal maintain, 80 kg" in text and "targets through 2026-09-18" in text


def test_render_is_byte_stable_and_shows_pending():
    p = Proposal.model_validate(
        {
            "id": "p1",
            "domain": "planning",
            "summary": "drop",
            "changes": [{"op": "delete", "tp_workout_id": "w1", "reason": "r"}],
        }
    )
    ctx = CoachContext(
        today=date(2026, 9, 16),
        thresholds={
            "ftp_watts": 250,
            "run_threshold_pace_sec_per_km": 270,
            "swim_css_sec_per_100m": 100,
            "lthr_bpm": 165,
            "max_hr_bpm": 190,
        },
        phase="active",
        goal=None,
        plan=None,
        this_week=None,
        actual_tss=123.0,
        actual_hours=4.5,
        designed_remaining=2,
        profile=None,
        targets_through=None,
        recent_days=[],
        pending=ChangeSet(narration="Knee pain: drop Wednesday.", proposals=[p]),
    )
    a, b = render_context(ctx), render_context(ctx)
    assert a == b
    assert "FTP 250 W" in a and "run threshold 4:30/km" in a and "swim CSS 1:40/100m" in a
    assert "Pending change set from an earlier turn (1 planning, 0 nutrition): Knee pain" in a
    assert "Recent load: not available." in a


async def test_labs_line_when_not_configured(nocommit, mem_store):
    ctx = await load_context(nocommit, mem_store, MONDAY, None)
    assert ctx.labs_enabled is False and ctx.labs is None
    assert "Labs: not configured (set TRI_ATHLETE_SEX" in render_context(ctx)


async def test_labs_line_in_each_stored_state(ldb, mem_store, registry):
    ctx = await load_context(ldb, mem_store, MONDAY, None, labs_enabled=True)
    assert ctx.labs is None
    assert "Labs: no panels stored (tri-wellness ingest)." in render_context(ctx)

    pid = seed_panel(ldb, date(2026, 8, 30), [("ferritin", 18.0, "ng/mL"), ("hs_crp", 0.4, "mg/L")])
    ctx = await load_context(ldb, mem_store, MONDAY, None, labs_enabled=True)
    assert ctx.labs is not None and ctx.labs.panel_id == pid and ctx.labs.report_on is None
    assert "Labs: latest panel 2026-08-30 (Quest) has no report yet (run tri-wellness report)." in (
        render_context(ctx)
    )

    findings = [
        Finding(
            marker="ferritin",
            display="Ferritin",
            system="iron",
            value=18.0,
            unit="ng/mL",
            conventional_status="in_range",
            functional_status="low",
            functional_range=(50.0, 150.0),
        ),
        Finding(
            marker="hs_crp",
            display="hs-CRP",
            system="inflammation",
            value=0.4,
            unit="mg/L",
            conventional_status="in_range",
            functional_status="optimal",
            functional_range=(None, 1.0),
        ),
    ]
    wrepo.insert_report(ldb, pid, registry.version, findings, REPORT_OK)
    ctx = await load_context(ldb, mem_store, MONDAY, None, labs_enabled=True)
    text = render_context(ctx)
    assert ctx.labs is not None and ctx.labs.outside_optimal == 1 and ctx.labs.markers == 2
    assert "Labs: panel 2026-08-30 (Quest), report " in text
    assert "1 of 2 markers outside optimal. Priorities: " in text
    assert text.index("Nutrition:") < text.index("Labs:")
    assert render_context(ctx) == text  # byte-stable
