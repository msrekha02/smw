"""The digest token.

An HMAC-signed payload carries the observed prices to the client and back, so
the ack checkpoints exactly the numbers the user looked at rather than whatever
the price is at ack time. No server-side storage, so the core mechanic has no
Redis dependency.

Per-ticker `at` timestamps, because a digest mixes a WebSocket price from two
seconds ago with a cold-tier close from yesterday. Checkpointing both at a
single digest-level timestamp leaves the cold one's price stale while its
timestamp claims now, and the next visit measures a diff that never happened.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass

from api.config import DIGEST_TOKEN_TTL_S, settings


class TokenError(ValueError):
    pass


@dataclass(frozen=True)
class Observed:
    px: float
    bench: float
    bt: str          # benchmark ticker the price was compared against
    at: dt.datetime  # when THIS ticker's price was observed


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(body: bytes) -> str:
    secret = settings.digest_token_secret.encode()
    return _b64e(hmac.new(secret, body, hashlib.sha256).digest())


def issue(
    user_id: uuid.UUID,
    observed: dict[str, Observed],
    as_of: dt.datetime,
    ttl_s: int = DIGEST_TOKEN_TTL_S,
) -> str:
    payload = {
        "uid": str(user_id),
        "as_of": as_of.astimezone(dt.timezone.utc).isoformat(),
        "exp": int(time.time()) + ttl_s,
        "p": {
            t: {
                "px": round(o.px, 6),
                "bench": round(o.bench, 6),
                "bt": o.bt,
                "at": o.at.astimezone(dt.timezone.utc).isoformat(),
            }
            for t, o in observed.items()
        },
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return f"{_b64e(body)}.{_sign(body)}"


def verify(token: str, user_id: uuid.UUID) -> dict[str, Observed]:
    """Signature, expiry, and caller identity. Any failure is a hard reject.

    Cross-user reuse is checked here rather than left to the ack UPDATE's
    `user_id` predicate: a token that silently checkpoints nothing looks
    identical to a working one from the client's side.
    """
    parts = token.split(".")
    if len(parts) != 2:
        raise TokenError("malformed token")
    try:
        body = _b64d(parts[0])
    except Exception as e:
        raise TokenError("malformed token body") from e
    if not hmac.compare_digest(_sign(body), parts[1]):
        raise TokenError("bad signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        raise TokenError("bad payload") from e

    if int(payload.get("exp", 0)) < int(time.time()):
        raise TokenError("token expired")
    if str(payload.get("uid")) != str(user_id):
        raise TokenError("token belongs to a different user")

    out: dict[str, Observed] = {}
    for t, v in (payload.get("p") or {}).items():
        try:
            out[t.upper()] = Observed(
                px=float(v["px"]),
                bench=float(v["bench"]),
                bt=str(v["bt"]),
                at=dt.datetime.fromisoformat(v["at"]),
            )
        except (KeyError, TypeError, ValueError) as e:
            raise TokenError(f"bad entry for {t}") from e
    return out


def as_of_of(token: str) -> dt.datetime | None:
    try:
        payload = json.loads(_b64d(token.split(".")[0]))
        return dt.datetime.fromisoformat(payload["as_of"])
    except Exception:
        return None
