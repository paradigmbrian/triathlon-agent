import logging
import uuid

import pytest
from langgraph.checkpoint.serde import jsonplus

from tri_core.config import Settings
from tri_core.harness.persistence import (
    SETUP_HINT,
    STORE_SETUP_HINT,
    checkpointer_ready,
    make_serde,
    open_checkpointer,
    open_store,
    store_ready,
)
from tri_core.testing.fakes import StateSample

UNREACHABLE = "postgresql://nobody:nothing@127.0.0.1:1/nope"
TAIL = (
    "run once per database:\n"
    "  uv run python scripts/setup_checkpointer.py $DATABASE_URL\n"
    "  uv run python scripts/setup_checkpointer.py $TEST_DATABASE_URL"
)


def test_setup_hints_keep_todays_text():
    assert SETUP_HINT == "checkpoint tables are missing; " + TAIL
    assert STORE_SETUP_HINT == "LangGraph store tables are missing; " + TAIL


def test_make_serde_round_trips_registered_models_without_the_unregistered_warning(caplog):
    jsonplus._warned_unregistered_types.clear()  # the warning fires once per process
    serde = make_serde([StateSample])
    value = {"pending": [StateSample(name="Ride", minutes=60)]}
    with caplog.at_level(logging.WARNING):
        back = serde.loads_typed(serde.dumps_typed(value))
    assert back == value
    assert not [r for r in caplog.records if "unregistered" in r.getMessage()]


def test_readiness_checks_are_false_when_the_database_is_unreachable():
    assert checkpointer_ready(UNREACHABLE) is False
    assert store_ready(UNREACHABLE) is False


@pytest.mark.db
async def test_checkpointer_and_store_open_against_the_test_database():
    url = Settings().test_database_url
    if not (checkpointer_ready(url) and store_ready(url)):
        pytest.skip("run scripts/setup_checkpointer.py against the test database")
    thread = {"configurable": {"thread_id": f"harness-{uuid.uuid4()}"}}
    async with open_checkpointer(url, [StateSample]) as saver:
        assert await saver.aget_tuple(thread) is None
    async with open_store(url) as store:
        assert await store.aget(("harness-test", str(uuid.uuid4())), "missing") is None
