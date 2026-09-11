import uuid
from datetime import date

import pytest
from langgraph.store.memory import InMemoryStore

from tri_core.config import Settings
from tri_nutrition import store as S
from tri_nutrition.nutrition.models import NutritionProfile, Product
from tri_nutrition.testing import PROFILE_ARGS


def profile(**over) -> NutritionProfile:
    return NutritionProfile(**{**PROFILE_ARGS, **over})


async def test_profile_round_trip_and_missing():
    mem = InMemoryStore()
    assert await S.get_profile(mem) is None
    await S.put_profile(mem, profile())
    back = await S.get_profile(mem)
    assert back == profile()
    item = await mem.aget(S.NAMESPACE, S.KEY_PROFILE)
    assert item is not None and item.value["weight_kg"] == PROFILE_ARGS["weight_kg"]


async def test_put_profile_seeds_product_library_from_tested_products():
    mem = InMemoryStore()
    gel = Product(name="Gel", form="gel", carbs_g=25)
    await S.put_profile(mem, profile(tested_products=[gel]))
    assert await S.get_product_library(mem) == [gel]
    # a second save adds new products and keeps existing ones
    mix = Product(name="Mix", form="drink", carbs_g=40)
    await S.put_profile(mem, profile(tested_products=[mix]))
    assert [p.name for p in await S.get_product_library(mem)] == ["Gel", "Mix"]


async def test_fuel_log_empty_and_forget_all():
    mem = InMemoryStore()
    assert await S.get_fuel_log(mem) == []
    await S.put_profile(mem, profile())
    assert await S.forget_all(mem) == 2  # profile + product_library
    assert await S.get_profile(mem) is None
    assert await S.forget_all(mem) == 0


async def test_postgres_store_round_trip():
    url = Settings().test_database_url
    if not S.store_ready(url):
        pytest.skip("run scripts/setup_checkpointer.py against the test database")
    ns = ("test", f"nutrition-{uuid.uuid4()}")
    async with S.open_store(url) as pg:
        try:
            await S.put_profile(pg, profile(), ns=ns)
            assert await S.get_profile(pg, ns=ns) == profile()
        finally:
            await S.forget_all(pg, ns=ns)


async def test_fuel_log_append_and_product_add():
    from tri_nutrition.nutrition.models import FuelLogEntry

    mem = InMemoryStore()
    assert await S.get_fuel_log(mem) == []
    e1 = FuelLogEntry(
        day=date(2026, 9, 7), sport="bike", duration_min=150, carbs_g_per_h=70, outcome="ok"
    )
    e2 = FuelLogEntry(
        day=date(2026, 9, 9),
        sport="run",
        duration_min=60,
        carbs_g_per_h=40,
        outcome="gi_upset",
        note="side stitch",
    )
    assert await S.append_fuel_entry(mem, e1) == 1
    assert await S.append_fuel_entry(mem, e2) == 2
    assert [e.outcome for e in await S.get_fuel_log(mem)] == ["ok", "gi_upset"]
    gel = Product(name="Gel", form="gel", carbs_g=25)
    assert await S.add_product(mem, gel) is True
    assert await S.add_product(mem, Product(name="Gel", form="gel", carbs_g=30)) is False
    assert await S.add_product(mem, Product(name="Chews", form="chew", carbs_g=24)) is True
    assert [p.name for p in await S.get_product_library(mem)] == ["Gel", "Chews"]
