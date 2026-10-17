"""Test doubles and fixtures shared by every package's tests."""

from tri_core.testing.fakes import ScriptedChatModel, tool_call
from tri_core.testing.loop import slow_connect, ticks_during
from tri_core.testing.rows import workout_row

__all__ = ["ScriptedChatModel", "slow_connect", "ticks_during", "tool_call", "workout_row"]
