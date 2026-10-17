"""Event-loop doubles: a connection that is slow to open, and a ticker that counts how often the
loop got to run while an awaitable was in flight. A blocked loop shows as few ticks."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import AbstractContextManager, contextmanager


def slow_connect[C](
    connect: Callable[[], AbstractContextManager[C]], seconds: float
) -> Callable[[], AbstractContextManager[C]]:
    """`connect`, but opening the connection blocks the calling thread for `seconds`."""

    @contextmanager
    def _connect() -> Iterator[C]:
        time.sleep(seconds)
        with connect() as conn:
            yield conn

    return _connect


async def ticks_during[T](awaitable: Awaitable[T], interval: float = 0.01) -> tuple[T, int]:
    """Await `awaitable` beside a ticker; return its result and the number of ticks."""
    ticks = 0
    done = asyncio.Event()

    async def tick() -> None:
        nonlocal ticks
        while not done.is_set():
            await asyncio.sleep(interval)
            ticks += 1

    ticker = asyncio.create_task(tick())
    try:
        result = await awaitable
    finally:
        done.set()
        await ticker
    return result, ticks
