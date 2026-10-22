"""Dhan credentials: the access token (JWT) carries the client ID and its expiry."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass

from ..errors import AuthenticationError

TOKEN_ENV_NAMES = ("DHAN_ACESS_TOKEN", "DHAN_ACCESS_TOKEN")


@dataclass(frozen=True, slots=True)
class Credentials:
    """Everything Dhan's REST and WebSocket APIs need to authenticate."""

    token: str
    client_id: str
    expires_at: float

    def __repr__(self) -> str:
        return f"Credentials(client_id={self.client_id!r}, expires_at={self.expires_at})"


def token_from_env(env: dict[str, str]) -> str:
    """The configured token, or an empty string.

    Accepts the common misspelling and strips surrounding quotes, which
    `docker --env-file` keeps as part of the value.
    """
    for name in TOKEN_ENV_NAMES:
        value = env.get(name, "").strip().strip("'\"").strip()
        if value:
            return value
    return ""


def credentials_from_token(token: str, client_id: str = "") -> Credentials:
    """Decode `token`; `client_id` overrides the one embedded in the token.

    Raises `AuthenticationError` for a malformed or already expired token.
    """
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        expires_at = float(claims["exp"])
        embedded_client_id = str(claims["dhanClientId"])
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise AuthenticationError("Dhan access token is not a valid JWT") from exc
    if expires_at <= time.time():
        raise AuthenticationError("Dhan access token has expired; generate a new one")
    return Credentials(token, client_id or embedded_client_id, expires_at)
