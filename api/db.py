"""Async engine / session plumbing.

The API uses the pooled `DATABASE_URL`; the worker uses `DATABASE_URL_DIRECT`.
Supabase's pooler runs pgbouncer in transaction mode, where session-scoped
behaviour (advisory locks, prepared statements, LISTEN/NOTIFY) is unreliable.
"""
from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from api.config import settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_prefer_direct = False


def use_direct() -> None:
    """Called once by the worker at boot.

    Supabase's pooler runs pgbouncer in transaction mode, where session-scoped
    behaviour is unreliable. Setting it process-wide beats threading a `direct`
    flag through every call site and getting it wrong in one of them.
    """
    global _prefer_direct
    _prefer_direct = True


def _normalise(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def get_engine(direct: bool = False) -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        url = settings.database_url_direct if (direct or _prefer_direct) else settings.database_url
        _engine = create_async_engine(
            _normalise(url),
            pool_size=10,
            max_overflow=10,
            pool_pre_ping=True,
            # pgbouncer transaction mode cannot serve server-side prepared
            # statements keyed per connection.
            connect_args={"statement_cache_size": 0} if "pooler" in url else {},
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker(direct: bool = False) -> async_sessionmaker[AsyncSession]:
    get_engine(direct)
    assert _sessionmaker is not None
    return _sessionmaker


@asynccontextmanager
async def session_scope(direct: bool = False) -> AsyncIterator[AsyncSession]:
    maker = get_sessionmaker(direct)
    async with maker() as s:
        try:
            yield s
            await s.commit()
        except Exception:
            await s.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    maker = get_sessionmaker()
    async with maker() as s:
        yield s


SCHEMA_DIR = pathlib.Path(__file__).resolve().parent.parent / "db"
# db/init/ holds cluster-level bootstrap for the Postgres image, not schema.


async def run_migrations(direct: bool = True) -> None:
    """Apply every db/*.sql in name order. Each file is idempotent.

    Executed on the raw asyncpg connection rather than through SQLAlchemy:
    asyncpg wraps `execute` in a prepared statement, and a prepared statement
    cannot carry multiple commands. The simple query protocol can.
    """
    engine = get_engine(direct)
    files = sorted(SCHEMA_DIR.glob("*.sql"))
    async with engine.begin() as conn:
        raw = await conn.get_raw_connection()
        driver = raw.driver_connection
        for f in files:
            sql = f.read_text(encoding="utf-8")
            if hasattr(driver, "execute"):
                await driver.execute(sql)
            else:  # pragma: no cover - non-asyncpg drivers
                await conn.execute(text(sql))


def reset_engine() -> None:
    """Drop the cached engine WITHOUT awaiting it.

    asyncpg connections are bound to the event loop that created them. Tests get
    a fresh loop per function, so an engine carried across them raises "Event
    loop is closed" from inside the pool's teardown.
    """
    global _engine, _sessionmaker
    _engine, _sessionmaker = None, None


async def dispose() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine, _sessionmaker = None, None
