"""The read endpoints keep the event loop free while the database works, so a coach turn's
stream keeps flowing during a Today or Progress load."""

from dataclasses import replace

import pytest

from tri_core.testing import slow_connect, ticks_during
from tri_planning.testing import MONDAY
from tri_web.progress import build_progress
from tri_web.today import build_today

pytestmark = pytest.mark.db

SLOW = 0.3  # seconds to open a connection; the loop ticks every 0.01 s when it is free


async def test_today_reads_the_database_off_the_event_loop(nocommit, runtime):
    rt = runtime(today=MONDAY)
    rt = replace(rt, connect=slow_connect(rt.connect, SLOW))
    view, ticks = await ticks_during(build_today(rt))
    assert view.header.today == MONDAY
    assert ticks >= 10


async def test_progress_reads_the_database_off_the_event_loop(nocommit, runtime):
    rt = runtime(today=MONDAY)
    rt = replace(rt, connect=slow_connect(rt.connect, SLOW))
    view, ticks = await ticks_during(build_progress(rt, "12m"))
    assert view.range == "12m"
    assert ticks >= 10
