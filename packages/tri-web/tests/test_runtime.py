"""open_runtime is the CLI's assembly without Typer: readiness first, then servers, saver, store,
deps, graph. The graph is opened over the test database with a scripted model."""

import pytest

from tri_coach.graph.checkpointer import checkpointer_ready
from tri_core.config import Settings
from tri_core.harness.persistence import store_ready
from tri_core.testing import ScriptedChatModel
from tri_web.config import WebSettings
from tri_web.runtime import Runtime, cfg, open_runtime

pytestmark = pytest.mark.db


async def test_readiness_failure_raises_with_the_cli_hint():
    settings = WebSettings(_env_file=None, anthropic_api_key=None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is not set"):
        async with open_runtime(settings, no_live=True, log=lambda m: None):
            pass


async def test_no_live_runtime_opens_the_graph_on_thread_coach(db):
    url = Settings().test_database_url
    if not (checkpointer_ready(url) and store_ready(url)):
        pytest.skip("checkpoint or store tables missing in the test database")
    settings = WebSettings(_env_file=None, anthropic_api_key="test-key", database_url=url)
    logged: list[str] = []
    async with open_runtime(
        settings, no_live=True, log=logged.append, model=ScriptedChatModel(script=[])
    ) as rt:
        assert isinstance(rt, Runtime)
        assert rt.thread_id == "coach" and rt.live is False and rt.running is None
        assert not rt.lock.locked()
        assert rt.servers.garmin_tools == [] and rt.servers.tp_tools == []
        assert cfg(rt) == {"configurable": {"thread_id": "coach"}}
        snap = await rt.graph.aget_state(cfg(rt))
        assert snap.next == () or snap.next == ("review",)  # a real thread may be paused
        with rt.connect() as conn:
            assert conn.execute("select 1 as one").fetchone()["one"] == 1
    assert logged == []  # --no-live starts no server, so nothing is logged
