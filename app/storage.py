from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .config import get_settings


async def _get_connection() -> psycopg.AsyncConnection:
    settings = get_settings()
    return await psycopg.AsyncConnection.connect(settings.database_url, row_factory=dict_row)


def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)

    if isinstance(row.get("created_at"), datetime):
        row["created_at"] = row["created_at"].isoformat()

    return row


async def init_db() -> None:
    async with await _get_connection() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS generations (
                id SERIAL PRIMARY KEY,
                topic TEXT NOT NULL,
                blog_post TEXT NOT NULL DEFAULT '',
                extras TEXT NOT NULL DEFAULT '',
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )

        # Backfill columns for tables that existed before the token-usage
        # feature was added, so upgrades don't require a manual migration.
        for column, definition in (
            ("input_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("output_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("total_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("cost_usd", "DOUBLE PRECISION NOT NULL DEFAULT 0"),
        ):
            await conn.execute(
                f"ALTER TABLE generations ADD COLUMN IF NOT EXISTS {column} {definition}"
            )


async def save_generation(
    topic: str,
    blog_post: str,
    extras: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    cost_usd: float = 0.0,
) -> int:
    async with await _get_connection() as conn:
        cur = await conn.execute(
            """
            INSERT INTO generations (
                topic, blog_post, extras,
                input_tokens, output_tokens, total_tokens, cost_usd,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                topic,
                blog_post,
                extras,
                input_tokens,
                output_tokens,
                total_tokens,
                cost_usd,
                datetime.now(timezone.utc),
            ),
        )
        row = await cur.fetchone()
        return row["id"]


async def list_generations(limit: int = 20) -> list[dict[str, Any]]:
    async with await _get_connection() as conn:
        cur = await conn.execute(
            """
            SELECT id, topic, total_tokens, cost_usd, created_at
            FROM generations
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = await cur.fetchall()
        return [_row_to_dict(row) for row in rows]


async def get_generation(generation_id: int) -> dict[str, Any] | None:
    async with await _get_connection() as conn:
        cur = await conn.execute(
            """
            SELECT id, topic, blog_post, extras,
                   input_tokens, output_tokens, total_tokens, cost_usd,
                   created_at
            FROM generations
            WHERE id = %s
            """,
            (generation_id,),
        )
        row = await cur.fetchone()
        return _row_to_dict(row) if row is not None else None