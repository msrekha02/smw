from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys
import uuid

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PROVIDER_MODE", "replay")
os.environ.setdefault("DIGEST_TOKEN_SECRET", "test-secret")
os.environ.setdefault("FIXTURES_DIR", str(ROOT / "fixtures"))

from api.calendar_ny import UTC, get_calendar  # noqa: E402

# A SEPARATE database by default. Several integrity tests truncate tables to
# get a clean slate, and pointing them at the development database would delete
# whatever you were looking at. `db/init/00_test_db.sql` creates it.
DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://smw:smw@localhost:5432/smw_test"
)


@pytest.fixture(scope="session")
def cal():
    return get_calendar()


def utc(y, m, d, hh=0, mm=0) -> dt.datetime:
    return dt.datetime(y, m, d, hh, mm, tzinfo=UTC)


def et(y, m, d, hh=0, mm=0) -> dt.datetime:
    from api.calendar_ny import ET

    return dt.datetime(y, m, d, hh, mm, tzinfo=ET)


# ---------------------------------------------------------------------------
# Database-backed tests skip cleanly when no Postgres is reachable, so the pure
# maths suite still runs anywhere.
# ---------------------------------------------------------------------------


def _db_reachable() -> bool:
    """A plain socket probe.

    Deliberately not an async connect: pytest-asyncio owns the event loop for
    the whole session, and calling `asyncio.run` from a sync fixture closes a
    loop the async tests are still going to need.
    """
    import socket
    from urllib.parse import urlparse

    u = urlparse(DB_URL.replace("postgresql+asyncpg", "postgresql"))
    try:
        with socket.create_connection((u.hostname or "localhost", u.port or 5432), 1.5):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def has_db() -> bool:
    return _db_reachable()


@pytest.fixture
async def db(has_db):
    """A database module bound to THIS test's event loop.

    The engine is a process global, and asyncpg connections belong to the loop
    that opened them, so it is created and torn down inside each test rather
    than shared across the session.
    """
    if not has_db:
        pytest.skip("no Postgres at TEST_DATABASE_URL")
    from api import cache
    from api import db as dbmod
    from api.config import settings

    settings.database_url = DB_URL
    settings.database_url_direct = DB_URL
    dbmod.reset_engine()
    try:
        yield dbmod
    finally:
        await dbmod.dispose()
        await cache.close()


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()
