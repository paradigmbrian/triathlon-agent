"""Create LangGraph's checkpoint and store tables. Brian runs this once per database; the app
never does DDL.

uv run python scripts/setup_checkpointer.py postgresql://tri_analyze:tri_analyze@localhost:5435/tri_analyze
"""

import asyncio
import sys

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore


async def main(url: str) -> None:
    async with AsyncPostgresSaver.from_conn_string(url) as saver:
        await saver.setup()
    async with AsyncPostgresStore.from_conn_string(url) as store:
        await store.setup()
    print(f"checkpoint and store tables ready in {url.rsplit('/', 1)[-1]}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1]))
