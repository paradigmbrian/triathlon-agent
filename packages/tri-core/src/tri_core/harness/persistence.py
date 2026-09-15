"""Postgres persistence for every graph. The checkpointer makes `interrupt()` durable: every
super-step writes a checkpoint keyed by thread_id, and `Command(resume=...)` in a fresh process
picks up from it. The Store holds what must outlive any thread. The app never creates tables;
scripts/setup_checkpointer.py does."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.store.postgres.aio import AsyncPostgresStore

SETUP_HINT = (
    "checkpoint tables are missing; run once per database:\n"
    "  uv run python scripts/setup_checkpointer.py $DATABASE_URL\n"
    "  uv run python scripts/setup_checkpointer.py $TEST_DATABASE_URL"
)

STORE_SETUP_HINT = (
    "LangGraph store tables are missing; run once per database:\n"
    "  uv run python scripts/setup_checkpointer.py $DATABASE_URL\n"
    "  uv run python scripts/setup_checkpointer.py $TEST_DATABASE_URL"
)


def make_serde(state_types: Sequence[type]) -> JsonPlusSerializer:
    """A serializer that accepts the pydantic models a graph keeps in its state. Registering them
    keeps the checkpointer from warning (and, in strict mode, refusing) when it loads them."""
    return JsonPlusSerializer(allowed_msgpack_modules=tuple(state_types))


@asynccontextmanager
async def open_checkpointer(
    url: str, state_types: Sequence[type]
) -> AsyncIterator[AsyncPostgresSaver]:
    async with AsyncPostgresSaver.from_conn_string(url, serde=make_serde(state_types)) as saver:
        yield saver


def checkpointer_ready(url: str) -> bool:
    try:
        with psycopg.connect(url) as conn:
            row = conn.execute("select to_regclass('public.checkpoints') as t").fetchone()
    except psycopg.OperationalError:
        return False
    return bool(row and row[0])


@asynccontextmanager
async def open_store(url: str) -> AsyncIterator[AsyncPostgresStore]:
    async with AsyncPostgresStore.from_conn_string(url) as store:
        yield store


def store_ready(url: str) -> bool:
    try:
        with psycopg.connect(url) as conn:
            row = conn.execute("select to_regclass('public.store') as t").fetchone()
    except psycopg.OperationalError:
        return False
    return bool(row and row[0])
