"""The athlete's long-term nutrition memory: LangGraph Store namespace, keys and typed access.

Everything here is async because AsyncPostgresStore refuses synchronous calls from the event
loop thread. The same helpers work on InMemoryStore in tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from langgraph.store.base import BaseStore
from langgraph.store.postgres.aio import AsyncPostgresStore

from tri_nutrition.nutrition.models import FuelLogEntry, NutritionProfile, Product

NAMESPACE: tuple[str, str] = ("athlete", "nutrition")
KEY_PROFILE = "profile"
KEY_FUEL_LOG = "fuel_log"
KEY_PRODUCTS = "product_library"
KEYS = (KEY_PROFILE, KEY_FUEL_LOG, KEY_PRODUCTS)

STORE_SETUP_HINT = (
    "LangGraph store tables are missing; run once per database:\n"
    "  uv run python scripts/setup_checkpointer.py $DATABASE_URL\n"
    "  uv run python scripts/setup_checkpointer.py $TEST_DATABASE_URL"
)


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


async def get_profile(store: BaseStore, ns: tuple[str, ...] = NAMESPACE) -> NutritionProfile | None:
    item = await store.aget(ns, KEY_PROFILE)
    return NutritionProfile.model_validate(item.value) if item else None


async def get_product_library(store: BaseStore, ns: tuple[str, ...] = NAMESPACE) -> list[Product]:
    item = await store.aget(ns, KEY_PRODUCTS)
    return [Product.model_validate(p) for p in item.value.get("products", [])] if item else []


async def put_product_library(
    store: BaseStore, products: list[Product], ns: tuple[str, ...] = NAMESPACE
) -> None:
    await store.aput(ns, KEY_PRODUCTS, {"products": [p.model_dump(mode="json") for p in products]})


async def put_profile(
    store: BaseStore, profile: NutritionProfile, ns: tuple[str, ...] = NAMESPACE
) -> None:
    """Overwrite the profile and merge its tested products into the product library by name."""
    await store.aput(ns, KEY_PROFILE, profile.model_dump(mode="json"))
    library = await get_product_library(store, ns)
    known = {p.name for p in library}
    added = [p for p in profile.tested_products if p.name not in known]
    if added or not library:
        await put_product_library(store, library + added, ns)


async def get_fuel_log(store: BaseStore, ns: tuple[str, ...] = NAMESPACE) -> list[FuelLogEntry]:
    item = await store.aget(ns, KEY_FUEL_LOG)
    return [FuelLogEntry.model_validate(e) for e in item.value.get("entries", [])] if item else []


async def forget_all(store: BaseStore, ns: tuple[str, ...] = NAMESPACE) -> int:
    n = 0
    for key in KEYS:
        if await store.aget(ns, key) is not None:
            await store.adelete(ns, key)
            n += 1
    return n


async def append_fuel_entry(
    store: BaseStore, entry: FuelLogEntry, ns: tuple[str, ...] = NAMESPACE
) -> int:
    """Add one entry to the fuel log; returns the log's new length."""
    entries = await get_fuel_log(store, ns)
    entries.append(entry)
    await store.aput(ns, KEY_FUEL_LOG, {"entries": [e.model_dump(mode="json") for e in entries]})
    return len(entries)


async def add_product(store: BaseStore, product: Product, ns: tuple[str, ...] = NAMESPACE) -> bool:
    """Add a product to the library unless one with that name exists; True when added."""
    library = await get_product_library(store, ns)
    if any(p.name == product.name for p in library):
        return False
    await put_product_library(store, [*library, product], ns)
    return True
