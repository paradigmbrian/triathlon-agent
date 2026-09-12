"""Postgres-backed checkpointing so a paused review survives process exit.

The checkpointer is what makes `interrupt()` durable. Every super-step writes a checkpoint
keyed by thread_id; `Command(resume=...)` in a fresh process picks up from it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from tri_coach.models import (
    ApplyReport,
    Brief,
    ChangeSet,
    Proposal,
    ProposalRequest,
    ReviewDecision,
)
from tri_nutrition.nutrition.models import NutritionChange
from tri_planning.planning.models import CalendarChange, PlannedSession

# Pydantic models that live in CoachState. Registering them keeps the checkpointer from
# warning (and, in strict mode, refusing) when it deserializes them.
STATE_TYPES: tuple[type, ...] = (
    Brief,
    Proposal,
    ProposalRequest,
    ChangeSet,
    ReviewDecision,
    ApplyReport,
    CalendarChange,
    PlannedSession,
    NutritionChange,
)

SETUP_HINT = (
    "checkpoint tables are missing; run once per database:\n"
    "  uv run python scripts/setup_checkpointer.py $DATABASE_URL\n"
    "  uv run python scripts/setup_checkpointer.py $TEST_DATABASE_URL"
)


def make_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES)


@asynccontextmanager
async def open_checkpointer(url: str) -> AsyncIterator[AsyncPostgresSaver]:
    async with AsyncPostgresSaver.from_conn_string(url, serde=make_serde()) as saver:
        yield saver


def checkpointer_ready(url: str) -> bool:
    try:
        with psycopg.connect(url) as conn:
            row = conn.execute("select to_regclass('public.checkpoints') as t").fetchone()
    except psycopg.OperationalError:
        return False
    return bool(row and row[0])
