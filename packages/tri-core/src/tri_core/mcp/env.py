"""The environment an MCP server subprocess starts with."""

from __future__ import annotations

import os

from tri_core.mcp.servers import ServerSpec

# uvx needs PATH and HOME (the Garmin server's tokens live in ~/.garminconnect); TMPDIR and the
# locale keep temp files and text encoding the same as the parent's.
PASSTHROUGH = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")


def child_env(spec: ServerSpec) -> dict[str, str]:
    """The passthrough keys that are set, then spec.env on top. Nothing else from os.environ:
    the servers never see the Anthropic key, the database URLs or the LangSmith key."""
    env = {k: os.environ[k] for k in PASSTHROUGH if k in os.environ}
    return {**env, **spec.env}
