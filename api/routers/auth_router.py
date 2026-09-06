"""Sign-in.

There are exactly two identity paths and they are mutually exclusive. With
`SUPABASE_JWKS_URL` set, Supabase issues the JWT and this router only reports
who the bearer is; the local issuer is off and `POST /api/auth/login` 404s. With
it unset, the local HS256 issuer signs a token for any email, because
`docker compose up` with no keys has to boot a fully working product and JWKS
verification cannot work without a project.

Any email is accepted deliberately. This is a demonstration of per-user state
isolation, not of a login wall: the point is that two addresses get two
watchlists, not that a password was checked.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api import auth
from api.config import settings
from api.db import get_session
from api.schemas import AuthMode, LoginRequest, MeOut, TokenOut

log = logging.getLogger("smw.auth")
router = APIRouter(prefix="/auth", tags=["auth"])

DEV_NOTICE = (
    "Dev auth — any email signs in. Set SUPABASE_JWKS_URL to enable real "
    "JWT verification."
)

TOKEN_TTL_S = 86_400


@router.get("/mode", response_model=AuthMode)
async def mode() -> AuthMode:
    """What the sign-in screen is allowed to offer.

    Unauthenticated on purpose: the client has to know which of the two paths
    is live before it has a token to show anyone.
    """
    dev = auth.dev_auth_enabled()
    return AuthMode(
        mode="dev" if dev else "supabase",
        # Live providers switch the local issuer off even with no JWKS URL, so
        # the screen has to be told rather than inferring it from `mode`.
        local_login=dev and not settings.live,
        notice=DEV_NOTICE if dev else None,
    )


@router.post("/login", response_model=TokenOut)
async def login(
    body: LoginRequest, session: AsyncSession = Depends(get_session)
) -> TokenOut:
    if not auth.dev_auth_enabled():
        raise HTTPException(
            404,
            "local sign-in is off: SUPABASE_JWKS_URL is configured, so tokens "
            "come from Supabase",
        )
    email = auth.normalize_email(body.email)
    uid = auth.dev_user_id(email)
    try:
        token = auth.issue_dev_token(uid, email, ttl_s=TOKEN_TTL_S)
    except auth.DevAuthDisabled as e:
        raise HTTPException(403, str(e)) from e

    # Created here rather than on the first authenticated request, so the row
    # exists even if the user signs in and closes the tab.
    await auth.ensure_user_row(session, uid, email)
    await session.commit()
    log.info("dev sign-in: %s -> %s", email, uid)
    return TokenOut(
        user_id=uid, email=email, access_token=token, expires_in=TOKEN_TTL_S
    )


@router.get("/me", response_model=MeOut)
async def me(user: auth.Principal = Depends(auth.get_current_user)) -> MeOut:
    """Who the bearer token says you are.

    The client calls this on boot: a token in `localStorage` is a claim, and an
    expired or foreign one has to fail here rather than on the first page that
    happens to need data.
    """
    return MeOut(user_id=user.id, email=user.email, mode=user.mode)
