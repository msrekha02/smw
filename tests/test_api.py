"""The HTTP surface: search ranking, adds, the digest contract, and acks."""
from __future__ import annotations


import httpx
import pytest
from sqlalchemy import text

from api import clock
from api.calendar_ny import get_calendar

pytestmark = pytest.mark.asyncio(loop_scope="function")

DEMO_EMAIL = "apitest@example.com"
TICKERS = ["AAPL", "MSFT", "NVDA", "META", "BA", "DUK", "SPY"]


@pytest.fixture
async def client(db):
    from api.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=60
    ) as c:
        yield c


@pytest.fixture
async def seeded(db):
    """A user with a seeded watchlist, checkpointed at the previous close."""
    from scripts.seed_demo import run

    return await run(DEMO_EMAIL, TICKERS, back_sessions=1, dispose=False)


@pytest.fixture
async def auth(client, seeded):
    r = await client.post("/api/dev/token", params={"email": DEMO_EMAIL})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------------------------------------------------------------------
# Health and auth
# ---------------------------------------------------------------------------


async def test_healthz_reports_provider_and_auth_mode(client):
    h = (await client.get("/healthz")).json()
    assert h["ok"] is True
    assert h["provider_mode"] == "replay"
    assert h["auth_mode"] == "dev-hs256"


async def test_endpoints_require_a_bearer_token(client):
    for path in ("/api/digest", "/api/watchlist", "/api/search?q=aapl"):
        assert (await client.get(path)).status_code == 401
    assert (
        await client.get("/api/digest", headers={"Authorization": "Bearer nonsense"})
    ).status_code == 401


# ---------------------------------------------------------------------------
# Search and CRUD
# ---------------------------------------------------------------------------


async def test_search_ranks_the_exact_ticker_first(client, auth):
    rows = (await client.get("/api/search", params={"q": "aapl"}, headers=auth)).json()
    assert rows[0]["ticker"] == "AAPL", [r["ticker"] for r in rows[:5]]


async def test_search_matches_on_name_too(client, auth):
    rows = (await client.get("/api/search", params={"q": "nvidia"}, headers=auth)).json()
    assert "NVDA" in [r["ticker"] for r in rows]


async def test_add_list_and_remove(client, auth):
    add = await client.post("/api/watchlist", json={"ticker": "amd"}, headers=auth)
    assert add.status_code == 201
    body = add.json()
    assert body["ticker"] == "AMD"

    listed = (await client.get("/api/watchlist", headers=auth)).json()
    assert "AMD" in [i["ticker"] for i in listed]

    assert (await client.delete("/api/watchlist/AMD", headers=auth)).status_code == 204
    listed = (await client.get("/api/watchlist", headers=auth)).json()
    assert "AMD" not in [i["ticker"] for i in listed]


async def test_adding_an_already_seeded_ticker_costs_no_credit(client, auth):
    before = (await client.get("/api/quota", headers=auth)).json()
    r = await client.post("/api/watchlist", json={"ticker": "AAPL"}, headers=auth)
    after = (await client.get("/api/quota", headers=auth)).json()
    assert r.json()["status"] == "active"
    assert after["your_seed_credits_left"] == before["your_seed_credits_left"]


async def test_adding_an_unlisted_symbol_is_refused_with_a_reason(client, auth):
    r = await client.post("/api/watchlist", json={"ticker": "ZZZZQ"}, headers=auth)
    assert r.status_code == 404
    assert "US" in r.json()["detail"]


async def test_the_quota_endpoint_never_exposes_a_spendable_reserve(client, auth):
    q = (await client.get("/api/quota", headers=auth)).json()
    assert set(q["partitions"]) == {"reserved", "seeding", "catalog"}
    assert "not addressable" in q["note"]


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------


async def test_digest_returns_ranked_cards_with_reasons(client, auth):
    await client.get("/api/digest", headers=auth)      # warm the benchmark cache
    r = await client.get("/api/digest", headers=auth)
    assert r.status_code == 200
    d = r.json()

    assert d["counts"]["total"] == len(TICKERS)
    assert d["token"]
    assert r.headers["ETag"]
    assert int(r.headers["X-Next-Poll-After-Ms"]) in (20_000, 900_000)

    scored = [c for c in d["cards"] if c["state"] == "ok"]
    assert scored, d["cards"][:2]
    attentions = [c["attention"] for c in scored]
    assert attentions == sorted(attentions, reverse=True), "ranked on attention"
    for c in scored:
        assert c["reason"].endswith(".")
        assert c["decomposition"]["contributions"]
        assert c["freshness"]["source"]


async def test_repeat_polls_with_no_change_return_304(client, auth):
    """Once the data has settled, a poll that learns nothing costs a 304.

    The first request of a cold list also triggers the on-demand refresh, which
    is bounded by a two-second budget and may legitimately return before every
    benchmark has landed. So settle first, then assert -- otherwise this test
    measures the warm-up rather than the revalidation.
    """
    etag = None
    for _ in range(5):
        r = await client.get("/api/digest", headers=auth)
        if r.status_code == 200 and r.headers["ETag"] == etag:
            break
        etag = r.headers["ETag"]
    assert etag

    r2 = await client.get("/api/digest", headers={**auth, "If-None-Match": etag})
    assert r2.status_code == 304
    assert r2.headers["ETag"] == etag
    assert r2.content == b""
    assert int(r2.headers["X-Next-Poll-After-Ms"]) in (20_000, 900_000)


async def test_as_if_last_seen_gives_a_deterministic_historical_window(client, auth):
    cal = get_calendar()
    ref = cal.session_n_ago(5, clock.today_et())
    anchor = cal.bounds(ref).close_utc.isoformat()

    a = (
        await client.get(
            "/api/digest", params={"as_if_last_seen": anchor}, headers=auth
        )
    ).json()
    b = (
        await client.get(
            "/api/digest", params={"as_if_last_seen": anchor}, headers=auth
        )
    ).json()

    assert [c["ticker"] for c in a["cards"]] == [c["ticker"] for c in b["cards"]]
    assert [round(c["attention"], 9) for c in a["cards"]] == [
        round(c["attention"], 9) for c in b["cards"]
    ]
    scored = [c for c in a["cards"] if c["state"] == "ok"]
    assert scored[0]["decomposition"]["n_days"] >= 4


async def test_a_quiet_digest_still_says_something(client, auth):
    """Absence of signal is reported as a finding, not a blank screen."""
    d = (await client.get("/api/digest", headers=auth)).json()
    if d["quiet_summary"] is not None:
        assert "Nothing unusual" in d["quiet_summary"]
        assert d["cards"], "the three highest-attention names are still shown"


# ---------------------------------------------------------------------------
# Ack
# ---------------------------------------------------------------------------


async def test_ack_applies_then_reports_superseded(client, auth):
    d = (await client.get("/api/digest", headers=auth)).json()
    tok = d["token"]

    first = await client.post("/api/ack", json={"token": tok}, headers=auth)
    assert first.status_code == 200
    results = first.json()["results"]
    assert results
    assert set(results.values()) <= {"applied", "superseded", "not_found"}
    assert "applied" in results.values()

    again = (await client.post("/api/ack", json={"token": tok}, headers=auth)).json()
    assert set(again["results"].values()) == {"superseded"}, (
        "a zero-row update returning a bare 200 causes a silent re-ack loop"
    )


async def test_ack_can_target_a_subset(client, auth):
    d = (await client.get("/api/digest", headers=auth)).json()
    r = await client.post(
        "/api/ack", json={"token": d["token"], "tickers": ["AAPL"]}, headers=auth
    )
    assert set(r.json()["results"]) == {"AAPL"}


async def test_a_tampered_token_is_rejected(client, auth):
    d = (await client.get("/api/digest", headers=auth)).json()
    body, sig = d["token"].split(".")
    r = await client.post(
        "/api/ack", json={"token": f"{body}.{sig[:-2]}xx"}, headers=auth
    )
    assert r.status_code == 400
    assert "token" in r.json()["detail"]


async def test_another_users_token_is_rejected(client, auth, db):
    d = (await client.get("/api/digest", headers=auth)).json()
    other = (
        await client.post("/api/dev/token", params={"email": "someone-else@example.com"})
    ).json()
    r = await client.post(
        "/api/ack",
        json={"token": d["token"]},
        headers={"Authorization": f"Bearer {other['access_token']}"},
    )
    assert r.status_code == 400
    assert "different user" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Feedback and validation surfaces
# ---------------------------------------------------------------------------


async def test_feedback_is_recorded_and_reaches_the_calibration_page(client, auth, db):
    d = (await client.get("/api/digest", headers=auth)).json()
    card = next(c for c in d["cards"] if c["state"] == "ok")
    shown = clock.now().isoformat()

    r = await client.post(
        "/api/feedback",
        json={
            "events": [
                {
                    "ticker": card["ticker"], "tier": "critical",
                    "attention": card["attention"], "shown_at": shown,
                    "clicked_through": True, "thumb": 1,
                }
            ]
        },
        headers=auth,
    )
    assert r.status_code == 202

    from api.routers.calibration import precision_at_critical

    async with db.session_scope() as s:
        p = await precision_at_critical(s)
    assert p["critical_shown"] >= 1
    assert p["explicit_judgements"] >= 1
    assert p["precision"] == pytest.approx(1.0)


async def test_precision_is_null_rather_than_one_when_nothing_is_judged(db):
    from api.routers.calibration import precision_at_critical

    async with db.session_scope() as s:
        await s.execute(text("DELETE FROM digest_feedback"))
    async with db.session_scope() as s:
        p = await precision_at_critical(s)
    assert p["precision"] is None, "an unjudged critical is not a correct one"


async def test_ticker_detail_shows_the_residual_distribution(client, auth):
    d = (await client.get("/api/tickers/NVDA", headers=auth)).json()
    assert d["ticker"] == "NVDA"
    assert d["benchmark_ticker"] == "XLK"
    assert d["sample_days"] > 1000
    h = d["residual_hist"]
    assert h and sum(h["counts"]) > 0
    # Displayed for honesty about non-normality, never used for scoring.
    assert h["tail_3s"] > 0.0027, "the fixtures really are fat-tailed"
    assert "ECDF scoring is designed and not built" in d["scoring_note"]


async def test_calibration_reports_predicted_against_observed(client, auth):
    r = await client.get("/api/calibration", headers=auth)
    if r.status_code == 503:
        pytest.skip("no calibration artifact; run scripts/calibrate.py")
    c = r.json()
    assert c["universe"] >= 40
    assert c["observed"]["critical_per_week"] > 0
    assert c["predicted"]["critical_per_week"] > 0
    assert c["residual_summary"]["tail_3s"] > c["residual_summary"]["normal_tail_3s"]
    assert "precision_at_critical" in c
