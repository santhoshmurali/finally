"""Factory precedence: Dhan > Massive > simulator."""

import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.market.cache import PriceCache
from app.market.dhan.source import DhanDataSource
from app.market.factory import create_market_data_source, default_watchlist
from app.market.massive_client import MassiveDataSource
from app.market.seed_prices import NSE_DEFAULTS, US_DEFAULTS
from app.market.simulator import SimulatorDataSource

DHAN_ENV = {"DHANHQ_API_KEY": "tok", "DHANHQ_CLIENT_ID": "1000000001"}


def make(env):
    with patch.dict(os.environ, env, clear=True):
        return create_market_data_source(PriceCache())


class TestSelection:
    def test_dhan_when_both_credentials_set(self):
        source = make(DHAN_ENV)
        assert isinstance(source, DhanDataSource)
        assert source.name == "dhanhq"
        assert source.currency == "INR"

    def test_dhan_wins_over_massive(self):
        assert isinstance(make({**DHAN_ENV, "MASSIVE_API_KEY": "m"}), DhanDataSource)

    def test_massive_when_only_massive_key(self):
        assert isinstance(make({"MASSIVE_API_KEY": "m"}), MassiveDataSource)

    def test_simulator_by_default(self):
        assert isinstance(make({}), SimulatorDataSource)

    def test_blank_dhan_key_falls_through(self):
        assert isinstance(make({"DHANHQ_API_KEY": "   ", "DHANHQ_CLIENT_ID": "x"}), SimulatorDataSource)

    def test_blank_dhan_key_falls_through_to_massive(self):
        source = make({"DHANHQ_API_KEY": "", "MASSIVE_API_KEY": "m"})
        assert isinstance(source, MassiveDataSource)

    def test_missing_client_id_fails_fast(self):
        with pytest.raises(RuntimeError, match="DHANHQ_CLIENT_ID"):
            make({"DHANHQ_API_KEY": "tok"})

    def test_blank_client_id_fails_fast(self):
        with pytest.raises(RuntimeError, match="DHANHQ_CLIENT_ID"):
            make({"DHANHQ_API_KEY": "tok", "DHANHQ_CLIENT_ID": "  "})

    def test_client_id_alone_does_not_select_dhan(self):
        assert isinstance(make({"DHANHQ_CLIENT_ID": "1"}), SimulatorDataSource)


class TestDhanConfig:
    def test_poll_interval_and_cache_dir(self):
        source = make({**DHAN_ENV, "DHANHQ_POLL_INTERVAL": "5", "DHANHQ_CACHE_DIR": "/tmp/x"})
        assert source._interval == 5.0
        assert source._resolver._path == Path("/tmp/x/dhan-nse-eq-instruments.csv")

    def test_poll_interval_clamped(self):
        assert make({**DHAN_ENV, "DHANHQ_POLL_INTERVAL": "0.2"})._interval == 1.0

    def test_default_cache_dir(self):
        assert make(DHAN_ENV)._resolver._path == Path("/app/db/dhan-nse-eq-instruments.csv")

    def test_sandbox_base_url_warns(self, caplog):
        with caplog.at_level(logging.WARNING):
            make({**DHAN_ENV, "DHANHQ_BASE_URL": "https://sandbox.dhan.co/v2"})
        assert "sandbox" in caplog.text

    def test_custom_base_url_applied(self):
        source = make({**DHAN_ENV, "DHANHQ_BASE_URL": "https://example.test/v2"})
        assert str(source._client._http.base_url).startswith("https://example.test/v2")

    def test_credentials_sent_as_headers(self):
        headers = make(DHAN_ENV)._client._http.headers
        assert headers["access-token"] == "tok"
        assert headers["client-id"] == "1000000001"


class TestSimulatorSeed:
    def test_market_seed_passed_through(self):
        assert make({"MARKET_SEED": "42"})._seed == 42

    def test_no_seed_by_default(self):
        assert make({})._seed is None

    def test_blank_seed_ignored(self):
        assert make({"MARKET_SEED": " "})._seed is None


class TestDefaultWatchlist:
    def test_us_in_simulator_mode(self):
        with patch.dict(os.environ, {}, clear=True):
            assert default_watchlist() == US_DEFAULTS

    def test_nse_in_dhan_mode(self):
        with patch.dict(os.environ, DHAN_ENV, clear=True):
            assert default_watchlist() == NSE_DEFAULTS

    def test_returns_a_copy(self):
        with patch.dict(os.environ, {}, clear=True):
            default_watchlist().append("ZZZ")
            assert "ZZZ" not in default_watchlist()
