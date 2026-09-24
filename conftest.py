import os

import pytest

# Every graph run in the suite would be a LangSmith trace if tracing were on. The package CLIs
# load .env only inside their Typer callback, and load_dotenv never overrides a set variable, so
# this holds for the whole run whatever .env says. (5,000 traces in two days of tri-wellness work
# were the test suite.)
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

pytest_plugins = ["tri_core.testing.fixtures"]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live", action="store_true", default=False, help="run tests that hit real MCP servers"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="needs --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
