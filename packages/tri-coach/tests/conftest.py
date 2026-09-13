from __future__ import annotations

import pytest
from langgraph.store.memory import InMemoryStore

from tri_planning.testing import NoCommit


@pytest.fixture
def nocommit(db):
    return NoCommit(db)


@pytest.fixture
def mem_store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def ndb(nocommit):
    if nocommit.execute("select to_regclass('nutrition_targets') as t").fetchone()["t"] is None:
        pytest.skip("migrations/004_nutrition.sql not applied")
    return nocommit


@pytest.fixture
def make_deps(nocommit):
    from tri_coach.testing import make_test_deps

    def _make(**kw):
        return make_test_deps(nocommit, **kw)

    return _make


@pytest.fixture
def ldb(nocommit):
    if nocommit.execute("select to_regclass('lab_panels') as t").fetchone()["t"] is None:
        pytest.skip("migrations/005_wellness.sql not applied")
    return nocommit


@pytest.fixture
def registry():
    from tri_wellness.ranges.registry import load_registry

    return load_registry("male")
