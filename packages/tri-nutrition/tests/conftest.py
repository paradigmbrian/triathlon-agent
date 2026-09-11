from __future__ import annotations

import contextlib

import pytest
from langgraph.store.memory import InMemoryStore

from tri_nutrition.testing import MONDAY, FakeGarmin, FakeTp, NoCommit


@pytest.fixture
def fake_garmin() -> FakeGarmin:
    return FakeGarmin()


@pytest.fixture
def fake_tp() -> FakeTp:
    return FakeTp()


@pytest.fixture
def nocommit(db):
    return NoCommit(db)


@pytest.fixture
def mem_store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def make_deps(nocommit):
    from tri_core.config import Settings
    from tri_nutrition.graph.deps import GraphDeps

    def _make(model, *, garmin=None, tp=None, horizon=14, today=MONDAY) -> GraphDeps:
        return GraphDeps(
            model=model,
            connect=lambda: contextlib.nullcontext(nocommit),
            db_url=Settings().test_database_url,
            garmin=garmin,
            tp=tp,
            horizon_days=horizon,
            today=lambda: today,
        )

    return _make
