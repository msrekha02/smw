"""FastAPI application."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from api import auth, cache, clock, db
from api.calendar_ny import get_calendar
from api.config import settings
from api.routers import ack, auth_router, calibration, digest, tickers, watchlist
from providers import get_providers

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
)
log = logging.getLogger("smw.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.run_migrations(direct=True)
    log.info(
        "api up: providers=%s clock=%s",
        get_providers().mode,
        clock.now().isoformat(),
    )
    for note in get_providers().notes:
        log.warning("provider note: %s", note)
    yield
    await cache.close()
    await db.dispose()


app = FastAPI(
    title="Smart Market Watchlist",
    version="1.0.0",
    description=(
        "A watchlist that gets quieter as it gets smarter. It surfaces what is "
        "statistically unusual for that specific stock, since you last looked, "
        "net of what its sector did."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["ETag", "X-Next-Poll-After-Ms"],
)

app.include_router(auth_router.router, prefix="/api")
app.include_router(watchlist.router, prefix="/api")
app.include_router(digest.router, prefix="/api")
app.include_router(ack.router, prefix="/api")
app.include_router(tickers.router, prefix="/api")
app.include_router(calibration.router, prefix="/api")


@app.get("/healthz", tags=["ops"])
async def healthz() -> dict:
    prov = get_providers()
    cal = get_calendar()
    now = clock.now()
    async with db.session_scope() as s:
        spy_bars = (
            await s.execute(
                text("SELECT count(*) FROM ticker_daily_bar WHERE ticker='SPY'")
            )
        ).scalar_one()
        last_run = (
            await s.execute(
                text("SELECT run_date, status FROM job_run ORDER BY run_date DESC LIMIT 1")
            )
        ).first()
    return {
        "ok": True,
        "provider_mode": prov.mode,
        "provider_notes": prov.notes,
        "auth_mode": "dev-hs256" if auth.dev_auth_enabled() else "supabase-jwks",
        "redis": await cache.ping(),
        "now": now.isoformat(),
        "market_open": cal.is_open(now),
        "spy_bars": int(spy_bars),
        "last_nightly": {"run_date": str(last_run[0]), "status": last_run[1]}
        if last_run
        else None,
    }


@app.post("/api/dev/token", tags=["ops"])
async def dev_token(email: str = "you@example.com") -> dict:
    """The pre-UI sign-in, kept for scripts and `curl`.

    `POST /api/auth/login` is the same issuer with a JSON body and is what the
    web app uses. Both refuse to exist once a Supabase project is configured.
    """
    if not auth.dev_auth_enabled():
        raise HTTPException(404, "dev auth is off: SUPABASE_JWKS_URL is configured")
    uid = auth.dev_user_id(email)
    try:
        token = auth.issue_dev_token(uid, auth.normalize_email(email))
    except auth.DevAuthDisabled as e:
        raise HTTPException(403, str(e)) from e
    return {"user_id": str(uid), "email": auth.normalize_email(email), "access_token": token}
