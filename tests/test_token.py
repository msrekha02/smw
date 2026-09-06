"""The digest token.

It carries the observed prices to the client and back, so an ack checkpoints
exactly the numbers the user looked at rather than whatever the price is at ack
time. That makes forgery an authorisation problem, not a cosmetic one.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import time
import uuid

import pytest

from api import digest_token
from api.calendar_ny import UTC
from api.digest_token import Observed, TokenError

UID = uuid.uuid4()
OTHER = uuid.uuid4()


def sample() -> dict[str, Observed]:
    now = dt.datetime.now(UTC)
    return {
        "NVDA": Observed(176.0, 268.0, "XLK", now),
        # A different `at`, deliberately: a digest mixes a WebSocket price from
        # two seconds ago with a cold-tier close from yesterday.
        "AMD": Observed(158.0, 268.0, "XLK", now - dt.timedelta(hours=18)),
    }


def test_round_trip_preserves_per_ticker_timestamps():
    obs = sample()
    tok = digest_token.issue(UID, obs, dt.datetime.now(UTC))
    back = digest_token.verify(tok, UID)
    assert set(back) == {"NVDA", "AMD"}
    assert back["NVDA"].px == 176.0
    assert back["AMD"].bt == "XLK"
    assert back["NVDA"].at != back["AMD"].at
    assert abs((back["AMD"].at - obs["AMD"].at).total_seconds()) < 1


def test_tampering_with_the_payload_is_rejected():
    tok = digest_token.issue(UID, sample(), dt.datetime.now(UTC))
    body, sig = tok.split(".")
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    payload["p"]["NVDA"]["px"] = 1.0
    forged = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")
    with pytest.raises(TokenError, match="signature"):
        digest_token.verify(f"{forged}.{sig}", UID)


def test_cross_user_reuse_is_rejected():
    """Checked here rather than left to the ack UPDATE's user_id predicate: a
    token that silently checkpoints nothing looks identical to a working one."""
    tok = digest_token.issue(UID, sample(), dt.datetime.now(UTC))
    with pytest.raises(TokenError, match="different user"):
        digest_token.verify(tok, OTHER)


def test_expiry_is_enforced():
    tok = digest_token.issue(UID, sample(), dt.datetime.now(UTC), ttl_s=-1)
    with pytest.raises(TokenError, match="expired"):
        digest_token.verify(tok, UID)


def test_malformed_tokens_are_rejected():
    for bad in ("", "abc", "a.b.c", "!!.??"):
        with pytest.raises(TokenError):
            digest_token.verify(bad, UID)


def test_a_token_signed_with_another_secret_is_rejected():
    from api.config import settings

    tok = digest_token.issue(UID, sample(), dt.datetime.now(UTC))
    old = settings.digest_token_secret
    settings.digest_token_secret = "a-different-secret"
    try:
        with pytest.raises(TokenError, match="signature"):
            digest_token.verify(tok, UID)
    finally:
        settings.digest_token_secret = old


def test_issue_is_stable_for_the_same_inputs():
    at = dt.datetime.now(UTC)
    obs = sample()
    frozen = int(time.time())
    a = digest_token.issue(UID, obs, at, ttl_s=1800)
    b = digest_token.issue(UID, obs, at, ttl_s=1800)
    del frozen
    # Same payload, same signature: the ETag path depends on this.
    assert a.split(".")[1] == b.split(".")[1]
