"""Test doubles and fixtures shared by every package's tests."""

from tri_core.testing.fakes import ScriptedChatModel, tool_call
from tri_core.testing.rows import workout_row

__all__ = ["ScriptedChatModel", "tool_call", "workout_row"]
