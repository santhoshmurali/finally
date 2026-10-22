"""Chooses the price source from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping

from .cache import PriceCache
from .dhan.auth import credentials_from_token, token_from_env
from .dhan.source import DhanDataSource
from .interface import MarketDataSource
from .simulator import SimulatorDataSource


def create_market_source(
    cache: PriceCache, env: Mapping[str, str] | None = None
) -> MarketDataSource:
    """Dhan live data if a Dhan access token is configured, else the simulator.

    Environment:
      DHAN_ACESS_TOKEN   Dhan access token (JWT). `DHAN_ACCESS_TOKEN` also works.
      DHAN_CLIENT_ID     Optional; defaults to the client ID inside the token.
      MARKET_SEED        Optional integer; makes the simulator reproducible.

    Raises `AuthenticationError` if the configured token is malformed or expired.
    """
    env = os.environ if env is None else env
    token = token_from_env(env)
    if token:
        client_id = env.get("DHAN_CLIENT_ID", "").strip()
        return DhanDataSource(cache, credentials_from_token(token, client_id))
    seed = env.get("MARKET_SEED", "").strip()
    return SimulatorDataSource(cache, seed=int(seed) if seed else None)
