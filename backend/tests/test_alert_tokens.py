"""API-05: confirm and unsubscribe tokens (app/core/tokens.py, docs/alerts.md section 3)."""

from __future__ import annotations

import base64
import hashlib
import hmac

from app.core.tokens import is_well_formed, new_confirm_token, token_hash, unsubscribe_token

SECRET = "s" * 32
SUBSCRIPTION_ID = "01930000-0000-7000-8000-000000000001"


def test_confirm_token_is_43_base64url_chars_and_stored_only_as_its_hash():
    token, hashed = new_confirm_token()
    assert is_well_formed(token)
    assert hashed == hashlib.sha256(token.encode()).hexdigest() == token_hash(token)
    assert token not in hashed


def test_confirm_tokens_are_random():
    assert len({new_confirm_token()[0] for _ in range(50)}) == 50


def test_unsubscribe_token_is_rebuilt_from_secret_and_id():
    token = unsubscribe_token(SECRET, SUBSCRIPTION_ID)
    assert is_well_formed(token)
    assert token == unsubscribe_token(SECRET, SUBSCRIPTION_ID)  # the alert job can rebuild it
    assert token != unsubscribe_token(SECRET, "01930000-0000-7000-8000-000000000002")
    # A new secret invalidates every link already sent.
    assert token != unsubscribe_token("t" * 32, SUBSCRIPTION_ID)


def test_an_unsubscribe_token_is_not_a_bare_hmac_of_the_id():
    # Purpose-tagged, so the same secret signing anything else can't produce it.
    bare = hmac.new(SECRET.encode(), SUBSCRIPTION_ID.encode(), hashlib.sha256).digest()
    assert unsubscribe_token(SECRET, SUBSCRIPTION_ID) != base64.urlsafe_b64encode(bare).rstrip(b"=").decode()


def test_malformed_tokens_are_rejected():
    good = new_confirm_token()[0]
    for bad in ["", good[:-1], good + "A", good[:-1] + "=", good[:-1] + "+", good + "\n", " " + good[1:]]:
        assert not is_well_formed(bad), repr(bad)
