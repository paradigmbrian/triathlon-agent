from contextlib import asynccontextmanager

import pytest

from tri_core.mcp.client import McpToolClient
from tri_core.mcp.env import child_env
from tri_core.mcp.live_tools import _connection
from tri_core.mcp.servers import ServerSpec


@pytest.fixture
def shell(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/home/athlete")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("TMPDIR", raising=False)
    for secret in ("ANTHROPIC_API_KEY", "DATABASE_URL", "LANGSMITH_API_KEY", "TRI_MODEL"):
        monkeypatch.setenv(secret, "x")
    monkeypatch.setenv("GARMIN_PASSWORD", "from-shell")


def test_child_env_passes_only_the_passthrough_keys_and_the_spec(shell):
    spec = ServerSpec(name="g", command="uvx", args=[], env={"GARMIN_ENABLED_TOOLS": "a,b"})
    assert child_env(spec) == {
        "PATH": "/usr/bin",
        "HOME": "/home/athlete",
        "LANG": "en_US.UTF-8",
        "GARMIN_ENABLED_TOOLS": "a,b",
    }


def test_the_spec_wins_over_a_passthrough_key(shell):
    spec = ServerSpec(name="g", command="uvx", args=[], env={"HOME": "/elsewhere"})
    assert child_env(spec)["HOME"] == "/elsewhere"


def test_the_live_tools_connection_uses_child_env(shell):
    env = _connection(ServerSpec(name="g", command="uvx", args=[]))["env"]
    assert env is not None and "ANTHROPIC_API_KEY" not in env and env["HOME"] == "/home/athlete"


async def test_the_sync_client_launches_with_child_env(shell, monkeypatch):
    seen = []

    @asynccontextmanager
    async def fake_stdio_client(params):
        seen.append(params.env)
        raise RuntimeError("stop after launch")
        yield  # pragma: no cover

    monkeypatch.setattr("tri_core.mcp.client.stdio_client", fake_stdio_client)
    with pytest.raises(RuntimeError, match="stop after launch"):
        async with McpToolClient(ServerSpec(name="g", command="uvx", args=[])):
            pass
    assert seen and "DATABASE_URL" not in seen[0] and "GARMIN_PASSWORD" not in seen[0]
