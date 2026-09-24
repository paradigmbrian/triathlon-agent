"""The suite never traces to LangSmith, even after a CLI callback loads .env."""

import os

import dotenv
from langsmith import utils as ls_utils

from tri_core import cli


def test_tracing_is_off_for_the_whole_suite():
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert not ls_utils.tracing_is_enabled()


def test_the_cli_callback_cannot_switch_tracing_on(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("LANGSMITH_TRACING=true\nLANGSMITH_PROJECT=from-dotenv\n")
    monkeypatch.setattr(cli, "load_dotenv", lambda: dotenv.load_dotenv(env))
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    cli.main()
    assert os.environ["LANGSMITH_PROJECT"] == "from-dotenv"  # .env was read; the guard still won
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert not ls_utils.tracing_is_enabled()
