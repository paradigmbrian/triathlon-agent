import pytest

from tri_analyze.allowlist import GARMIN_LIVE_TOOLS, TP_LIVE_TOOLS
from tri_analyze.tools.live import open_live_tools
from tri_core.config import Settings


def test_allowlists_are_read_only_tools():
    for name in GARMIN_LIVE_TOOLS + TP_LIVE_TOOLS:
        assert name.startswith(("get_", "tp_get_"))


@pytest.mark.live
async def test_live_tools_bind_expected_names():
    async with open_live_tools(Settings(), print) as tools:
        names = [t.name for t in tools]
        assert names == GARMIN_LIVE_TOOLS + TP_LIVE_TOOLS
        readiness = next(t for t in tools if t.name == "get_training_readiness")
        text = await readiness.ainvoke({"date": "2026-09-06"})
        assert "score" in str(text)


@pytest.mark.live
async def test_live_stub_argument_names_equal_the_real_tools():
    from tri_analyze.evals.target import stub_tools

    stubs = {t.name: t for t in stub_tools({"live": True})}
    async with open_live_tools(Settings(), print) as tools:
        for real in tools:
            assert set(stubs[real.name].args) == set(real.args), real.name
