"""Credentials decoding from the Dhan access token."""

import base64
import json
import time

import pytest

from app.market.dhan.auth import credentials_from_token, token_from_env
from app.market.errors import AuthenticationError


def make_token(**claims):
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    return f"{part({'alg': 'HS512'})}.{part(claims)}.signature"


def test_client_id_and_expiry_come_from_token():
    exp = time.time() + 3600
    creds = credentials_from_token(make_token(exp=exp, dhanClientId="1100"))
    assert creds.client_id == "1100"
    assert creds.expires_at == exp


def test_explicit_client_id_overrides_token():
    token = make_token(exp=time.time() + 3600, dhanClientId="1100")
    assert credentials_from_token(token, client_id="999").client_id == "999"


def test_expired_token_is_rejected():
    with pytest.raises(AuthenticationError, match="expired"):
        credentials_from_token(make_token(exp=time.time() - 1, dhanClientId="1"))


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", make_token(exp=time.time() + 60)])
def test_malformed_token_is_rejected(token):
    with pytest.raises(AuthenticationError, match="valid JWT"):
        credentials_from_token(token)


def test_repr_hides_token():
    creds = credentials_from_token(make_token(exp=time.time() + 60, dhanClientId="1"))
    assert creds.token not in repr(creds)


def test_token_from_env_accepts_both_spellings():
    assert token_from_env({"DHAN_ACESS_TOKEN": " t1 "}) == "t1"
    assert token_from_env({"DHAN_ACCESS_TOKEN": "t2"}) == "t2"
    assert token_from_env({"DHAN_ACESS_TOKEN": "  "}) == ""
    assert token_from_env({}) == ""


@pytest.mark.parametrize("raw", ['"abc"', "'abc'", ' "abc" '])
def test_token_from_env_strips_surrounding_quotes(raw):
    assert token_from_env({"DHAN_ACESS_TOKEN": raw}) == "abc"


def test_jwt_payload_that_is_not_an_object_is_rejected():
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    with pytest.raises(AuthenticationError, match="valid JWT"):
        credentials_from_token(f"{part({})}.{part(['not', 'an', 'object'])}.sig")
