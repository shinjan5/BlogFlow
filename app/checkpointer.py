from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from .config import get_settings

_pool: AsyncConnectionPool | None = None
_checkpointer: AsyncPostgresSaver | None = None


async def init_checkpointer() -> AsyncPostgresSaver:
    global _pool, _checkpointer

    if _checkpointer is not None:
        return _checkpointer

    settings = get_settings()

    _pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        max_size=10,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=False,
    )
    await _pool.open()

    _checkpointer = AsyncPostgresSaver(_pool)
    await _checkpointer.setup()

    return _checkpointer


def get_checkpointer() -> AsyncPostgresSaver:
    if _checkpointer is None:
        raise RuntimeError(
            "Checkpointer not initialized — call init_checkpointer() "
            "during application startup before using it."
        )
    return _checkpointer


async def close_checkpointer() -> None:
    global _pool, _checkpointer

    if _pool is not None:
        await _pool.close()

    _pool = None
    _checkpointer = None

