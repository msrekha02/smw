"""Sign-in, and the isolation claim it exists to make demonstrable.

The system claims per-user state isolation and durable acks. Before there was a
sign-in UI those were claims about code nobody could exercise; these tests are
the assertion, and the two-user isolation test is the one that would fail if
`user_id` were ever dropped from a WHERE clause.
"""
from __future__ import annotations

import datetime as dt

import httpx
import pytest
from sqlalchemy import text

from api import clock

pytestmark = pytest.mark.asyncio(loop_scope="function")

SEED_EMAIL = "authtest@example.com"
SEED_TICKERS = ["AAPL", "MSFT", "NVDA", "BA", "SPY"]

A_EMAIL = "a@test.com"
B_EMAIL = "b@test.com"
A_TICKERS = ["AAPL", "MSFT", "NVDA"]
B_TICKERS = ["BA"]


@pytest.fixture
async def client(db):
    from api.main import app

    # `ASGITransport` does not run the lifespan, and the sign-in tests do not
    # go through `seed_demo`, so the schema is applied here.
    await db.run_migrations(direct=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=60
    ) as c:
        yield c


@pytest.fixture
async def seeded(db):
    """Tickers with baselines, so an add is instant and costs no credit."""
    from scripts.seed_demo import run

    return await run(SEED_EMAIL, SEED_TICKERS, back_sessions=1, dispose=False)


@pytest.fixture
async def fresh_users(db):
    """A and B start with no rows anywhere.

    The dev user id is derived from the email, so these two identities are the
    same across runs and would otherwise inherit the previous run's watchlist.
    `ON DELETE CASCADE` from `app_users` takes the items and snapshots with it.
    """
    from api import auth

    ids = [str(auth.dev_user_id(e)) for e in (A_EMAIL, B_EMAIL)]
    async with db.session_scope() as s:
        await s.execute(
            text("DELETE FROM app_users WHERE id::text = ANY(:ids)"), {"ids": ids}
        )
    return ids


async def signin(client: httpx.AsyncClient, email: str) -> dict:
    r = await client.post("/api/auth/login", json={"email": email})
    assert r.status_code == 200, r.text
    body = r.json()
    return {
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "user_id": body["user_id"],
        "email": body["email"],
    }


# ---------------------------------------------------------------------------
# The sign-in surface
# ---------------------------------------------------------------------------


async def test_mode_advertises_local_login_and_says_so_out_loud(client):
    m = (await client.get("/api/auth/mode")).json()
    assert m["mode"] == "dev"
    assert m["local_login"] is True
    assert "SUPABASE_JWKS_URL" in m["notice"]


async def test_any_email_signs_in_and_gets_its_own_user_row(client, fresh_users, db):
    a = await signin(client, A_EMAIL)
    b = await signin(client, B_EMAIL)
    assert a["user_id"] != b["user_id"]

    async with db.session_scope() as s:
        emails = (
            await s.execute(
                text("SELECT email FROM app_users WHERE id::text = ANY(:ids)"),
                {"ids": [a["user_id"], b["user_id"]]},
            )
        ).scalars().all()
    # The row is created by signing in, not by the first authenticated request.
    assert sorted(emails) == [A_EMAIL, B_EMAIL]


async def test_signing_in_twice_is_the_same_user(client):
    first = await signin(client, A_EMAIL)
    second = await signin(client, "  A@Test.COM ")
    assert first["user_id"] == second["user_id"], "case is not identity"
    assert second["email"] == A_EMAIL


async def test_me_reports_the_bearer_and_rejects_a_missing_one(client):
    a = await signin(client, A_EMAIL)
    me = (await client.get("/api/auth/me", headers=a["headers"])).json()
    assert me["email"] == A_EMAIL
    assert me["user_id"] == a["user_id"]
    assert me["mode"] == "dev"

    assert (await client.get("/api/auth/me")).status_code == 401
    assert (
        await client.get("/api/auth/me", headers={"Authorization": "Bearer nonsense"})
    ).status_code == 401


async def test_an_email_shaped_like_nothing_is_refused(client):
    r = await client.post("/api/auth/login", json={"email": "nope"})
    assert r.status_code == 422


async def test_configuring_supabase_takes_the_local_issuer_offline(client):
    """The two paths are mutually exclusive, and the switch is one env var.

    With a project configured there is no mode where the app will accept a
    token it minted for itself, so `/api/auth/login` has to stop existing rather
    than merely stop being advertised.
    """
    from api import auth
    from api.config import settings

    before = settings.supabase_jwks_url
    settings.supabase_jwks_url = "https://example.supabase.co/auth/v1/.well-known/jwks.json"
    try:
        assert auth.dev_auth_enabled() is False

        m = (await client.get("/api/auth/mode")).json()
        assert m["mode"] == "supabase"
        assert m["local_login"] is False
        assert m["notice"] is None

        assert (
            await client.post("/api/auth/login", json={"email": A_EMAIL})
        ).status_code == 404
        assert (
            await client.post("/api/dev/token", params={"email": A_EMAIL})
        ).status_code == 404

        # A token the local issuer signed is no longer identity either: the
        # JWKS path is the only verifier now.
        assert (
            await client.get(
                "/api/auth/me", headers={"Authorization": "Bearer whatever"}
            )
        ).status_code == 401
    finally:
        settings.supabase_jwks_url = before

    # And the switch is reversible in the same process.
    assert auth.dev_auth_enabled() is True
    assert (await client.get("/api/auth/mode")).json()["local_login"] is True


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


async def test_two_users_watchlists_and_snapshots_are_fully_isolated(
    client, seeded, fresh_users, db
):
    """The claim the whole sign-in exists to make demonstrable.

    A adds three tickers and acks its digest; B adds one and acks nothing.
    Neither `watchlist_items` nor `watchlist_snapshots` may leak in either
    direction, and A's acks must not move B's checkpoints.
    """
    a = await signin(client, A_EMAIL)
    b = await signin(client, B_EMAIL)

    for t in A_TICKERS:
        r = await client.post(
            "/api/watchlist", json={"ticker": t}, headers=a["headers"]
        )
        assert r.status_code == 201, r.text
    for t in B_TICKERS:
        r = await client.post(
            "/api/watchlist", json={"ticker": t}, headers=b["headers"]
        )
        assert r.status_code == 201, r.text

    # --- over the API ------------------------------------------------------
    a_listed = {
        i["ticker"]
        for i in (await client.get("/api/watchlist", headers=a["headers"])).json()
    }
    b_listed = {
        i["ticker"]
        for i in (await client.get("/api/watchlist", headers=b["headers"])).json()
    }
    assert a_listed == set(A_TICKERS)
    assert b_listed == set(B_TICKERS)
    assert not (a_listed & b_listed)

    a_cards = {
        c["ticker"]
        for c in (await client.get("/api/digest", headers=a["headers"])).json()["cards"]
    }
    b_cards = {
        c["ticker"]
        for c in (await client.get("/api/digest", headers=b["headers"])).json()["cards"]
    }
    assert a_cards == set(A_TICKERS)
    assert b_cards == set(B_TICKERS)

    # Both users are given an equally stale checkpoint, so that when A acks and
    # B does not, the only thing separating their rows is the `user_id` filter.
    stale = clock.now() - dt.timedelta(days=5)
    async with db.session_scope() as s:
        await s.execute(
            text(
                "UPDATE watchlist_snapshots SET last_seen_at = :at, is_initial = true"
                " WHERE user_id::text = ANY(:ids)"
            ),
            {"at": stale, "ids": [a["user_id"], b["user_id"]]},
        )

    # --- in the tables -----------------------------------------------------
    async with db.session_scope() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT user_id::text, ticker FROM watchlist_items"
                    " WHERE user_id::text = ANY(:ids)"
                ),
                {"ids": [a["user_id"], b["user_id"]]},
            )
        ).all()
        snaps = (
            await s.execute(
                text(
                    "SELECT user_id::text, ticker, last_seen_at, is_initial"
                    "  FROM watchlist_snapshots WHERE user_id::text = ANY(:ids)"
                ),
                {"ids": [a["user_id"], b["user_id"]]},
            )
        ).all()

    items: dict[str, set[str]] = {a["user_id"]: set(), b["user_id"]: set()}
    for uid, ticker in rows:
        items[uid].add(ticker)
    assert items[a["user_id"]] == set(A_TICKERS)
    assert items[b["user_id"]] == set(B_TICKERS)
    assert not (items[a["user_id"]] & items[b["user_id"]])

    snap_by_user: dict[str, dict] = {a["user_id"]: {}, b["user_id"]: {}}
    for uid, ticker, seen_at, is_initial in snaps:
        snap_by_user[uid][ticker] = (seen_at, is_initial)
    assert set(snap_by_user[a["user_id"]]) == set(A_TICKERS)
    assert set(snap_by_user[b["user_id"]]) == set(B_TICKERS)

    b_before = dict(snap_by_user[b["user_id"]])

    # --- A acks; only A's checkpoints move ---------------------------------
    d = (await client.get("/api/digest", headers=a["headers"])).json()
    acked = (
        await client.post("/api/ack", json={"token": d["token"]}, headers=a["headers"])
    ).json()["results"]
    assert "applied" in acked.values()

    async with db.session_scope() as s:
        after = (
            await s.execute(
                text(
                    "SELECT user_id::text, ticker, last_seen_at, is_initial"
                    "  FROM watchlist_snapshots WHERE user_id::text = ANY(:ids)"
                ),
                {"ids": [a["user_id"], b["user_id"]]},
            )
        ).all()

    a_after = {t: (at, init) for uid, t, at, init in after if uid == a["user_id"]}
    b_after = {t: (at, init) for uid, t, at, init in after if uid == b["user_id"]}

    assert set(a_after) == set(A_TICKERS)
    assert any(at > stale for at, _ in a_after.values()), "A's ack moved A forward"
    assert all(not init for _, init in a_after.values()), "A is past its checkpoint"
    assert b_after == b_before, "B's checkpoints were not touched by A's ack"


async def test_removing_a_ticker_leaves_the_other_users_copy_alone(
    client, seeded, fresh_users, db
):
    """Shared tickers, separate rows: `watchlist_items` is keyed on the pair."""
    a = await signin(client, A_EMAIL)
    b = await signin(client, B_EMAIL)
    for who in (a, b):
        await client.post(
            "/api/watchlist", json={"ticker": "AAPL"}, headers=who["headers"]
        )

    assert (
        await client.delete("/api/watchlist/AAPL", headers=a["headers"])
    ).status_code == 204

    a_listed = [
        i["ticker"]
        for i in (await client.get("/api/watchlist", headers=a["headers"])).json()
    ]
    b_listed = [
        i["ticker"]
        for i in (await client.get("/api/watchlist", headers=b["headers"])).json()
    ]
    assert "AAPL" not in a_listed
    assert "AAPL" in b_listed
