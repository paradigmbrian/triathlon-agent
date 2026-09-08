from __future__ import annotations

import contextlib

import pytest

from tri_planning.graph.deps import GraphDeps
from tri_planning.testing import MONDAY, FakeTp, NoCommit


@pytest.fixture
def fake_tp() -> FakeTp:
    return FakeTp()


@pytest.fixture
def nocommit(db):
    return NoCommit(db)


@pytest.fixture
def make_deps(nocommit):
    from tri_core.config import Settings

    def _make(model, *, tp=None, horizon=1, today=MONDAY, garmin_tools=None) -> GraphDeps:
        return GraphDeps(
            model=model,
            connect=lambda: contextlib.nullcontext(nocommit),
            db_url=Settings().test_database_url,
            tp=tp,
            garmin_tools=list(garmin_tools or []),
            horizon_weeks=horizon,
            today=lambda: today,
        )

    return _make
