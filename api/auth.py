"""Authentication.

Supabase Auth issues RS256 JWTs; we verify them against the project's JWKS.
When no `SUPABASE_JWKS_URL` is configured we fall back to a local HS256 issuer,
because `docker compose up` with no keys has to boot a fully working product and
JWKS verification cannot work without a project. The fallback is loud about
itself in `/healthz` and refuses to run when `PROVIDER_MODE=live`.
"""
from __future__ import annotations

import datetime as dt
import time
import uuid
from dataclasses import dataclass

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.db import get_session

_jwk_client: PyJWKClient | None = None
_jwk_client_url: str | None = None


@dataclass(frozen=True)
class Principal:
    id: uuid.UUID
    email: str | None = None
    mode: str = "supabase"


class DevAuthDisabled(RuntimeError):
    pass


def dev_auth_enabled() -> bool:
    """True when no Supabase project is configured.

    Setting `SUPABASE_JWKS_URL` flips the whole system to real JWT verification
    and takes the local issuer offline in the same move: there is no mode where
    both are live, so a deployment cannot be talked into accepting a token it
    minted for itself.
    """
    return not settings.supabase_jwks_url


def normalize_email(email: str) -> str:
    """Case and whitespace are not identity, so they are not part of the id."""
    return email.strip().lower()


def dev_user_id(email: str) -> uuid.UUID:
    """The dev identity of an email address.

    Derived rather than stored, so the same address is the same user across a
    `docker compose down -v`, and so `scripts/seed_demo.py` and a browser
    sign-in land on the same row without coordinating.
    """
    return uuid.uuid5(uuid.NAMESPACE_URL, f"smw-dev:{normalize_email(email)}")


async def ensure_user_row(session: AsyncSession, uid: uuid.UUID, email: str | None) -> None:
    """Create `app_users` if this identity has not been seen before.

    Supabase owns identity; `app_users` only holds what this system needs
    (quota counters, timezone), so the row is created on first sight rather
    than by a webhook that could be missed.
    """
    await session.execute(
        text(
            """
        INSERT INTO app_users (id, email, seed_credits_reset_on, created_at)
        VALUES (:id, :email, :today, :now)
        ON CONFLICT (id) DO NOTHING
        """
        ),
        {
            "id": uid,
            "email": email,
            "today": dt.date.today(),
            "now": dt.datetime.now(dt.timezone.utc),
        },
    )


def issue_dev_token(user_id: uuid.UUID, email: str | None = None, ttl_s: int = 86400) -> str:
    """Local development only. Never reachable when JWKS is configured."""
    if not dev_auth_enabled():
        raise DevAuthDisabled("dev auth is off because SUPABASE_JWKS_URL is set")
    if settings.live:
        raise DevAuthDisabled("dev auth is not available in live provider mode")
    now = int(time.time())
    return jwt.encode(
        {
            "sub": str(user_id),
            "email": email,
            "aud": settings.supabase_jwt_audience,
            "iat": now,
            "exp": now + ttl_s,
            "iss": "smw-dev",
        },
        settings.dev_auth_secret,
        algorithm="HS256",
    )


def _client() -> PyJWKClient:
    global _jwk_client, _jwk_client_url
    if _jwk_client is None or _jwk_client_url != settings.supabase_jwks_url:
        _jwk_client = PyJWKClient(settings.supabase_jwks_url, cache_keys=True)
        _jwk_client_url = settings.supabase_jwks_url
    return _jwk_client


def decode(token: str) -> dict:
    if dev_auth_enabled():
        return jwt.decode(
            token,
            settings.dev_auth_secret,
            algorithms=["HS256"],
            audience=settings.supabase_jwt_audience,
        )
    key = _client().get_signing_key_from_jwt(token).key
    return jwt.decode(
        token,
        key,
        algorithms=["RS256", "ES256"],
        audience=settings.supabase_jwt_audience,
    )


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized("missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = decode(token)
    except jwt.ExpiredSignatureError as e:
        raise _unauthorized("token expired") from e
    except (jwt.InvalidTokenError, httpx.HTTPError, Exception) as e:
        raise _unauthorized("invalid token") from e
    sub = claims.get("sub")
    if not sub:
        raise _unauthorized("token has no subject")
    try:
        uid = uuid.UUID(str(sub))
    except ValueError as e:
        raise _unauthorized("subject is not a uuid") from e
    return Principal(
        uid, claims.get("email"), "dev" if dev_auth_enabled() else "supabase"
    )


async def get_current_user(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Principal:
    """Verify the JWT and make sure the user row exists."""
    await ensure_user_row(session, principal.id, principal.email)
    await session.commit()
    return principal
