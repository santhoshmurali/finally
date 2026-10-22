"""Tests for previous_close, Bar, cache carry-forward and the extended interface."""

from datetime import date

import pytest

from app.market import CapabilityError, MarketDataError, UnknownTickerError
from app.market.cache import PriceCache
from app.market.interface import MarketDataSource
from app.market.models import Bar, PriceUpdate


class TestPreviousClose:
    def test_defaults_to_none(self):
        u = PriceUpdate("AAPL", 190.0, 190.0, 1.0)
        assert u.previous_close is None
        assert u.day_change is None
        assert u.day_change_percent is None

    def test_day_change(self):
        u = PriceUpdate("AAPL", 195.0, 194.0, 1.0, previous_close=190.0)
        assert u.day_change == 5.0
        assert u.day_change_percent == pytest.approx(2.6316, abs=1e-4)

    def test_negative_day_change(self):
        u = PriceUpdate("AAPL", 180.0, 181.0, 1.0, previous_close=200.0)
        assert u.day_change == -20.0
        assert u.day_change_percent == -10.0

    def test_zero_previous_close_has_no_percent(self):
        u = PriceUpdate("AAPL", 10.0, 10.0, 1.0, previous_close=0.0)
        assert u.day_change_percent is None

    def test_tick_direction_is_independent_of_previous_close(self):
        u = PriceUpdate("AAPL", 189.0, 188.0, 1.0, previous_close=190.0)
        assert u.direction == "up"  # vs previous tick
        assert u.day_change < 0  # vs previous close

    def test_to_dict_includes_day_fields_and_legacy_keys(self):
        d = PriceUpdate("AAPL", 195.0, 194.0, 1.0, previous_close=190.0).to_dict()
        assert d["previous_close"] == 190.0
        assert d["day_change"] == 5.0
        assert d["day_change_percent"] == pytest.approx(2.6316, abs=1e-4)
        for key in ("ticker", "price", "previous_price", "timestamp", "change",
                    "change_percent", "direction"):
            assert key in d

    def test_to_dict_with_unknown_previous_close(self):
        d = PriceUpdate("AAPL", 195.0, 194.0, 1.0).to_dict()
        assert d["previous_close"] is None
        assert d["day_change_percent"] is None


class TestBar:
    def test_to_dict(self):
        b = Bar(date(2026, 10, 21), 1.0, 2.0, 0.5, 1.5, 1000)
        assert b.to_dict() == {
            "date": "2026-10-21",
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 1000,
        }

    def test_immutable(self):
        b = Bar(date(2026, 10, 21), 1.0, 2.0, 0.5, 1.5, 1000)
        with pytest.raises(AttributeError):
            b.close = 3.0


class TestCachePreviousClose:
    def test_old_signature_still_works(self):
        cache = PriceCache()
        u = cache.update("AAPL", 190.0)
        assert u.previous_close is None

    def test_stores_and_rounds_previous_close(self):
        cache = PriceCache()
        u = cache.update("AAPL", 190.0, previous_close=189.456)
        assert u.previous_close == 189.46
        assert cache.get("AAPL").previous_close == 189.46

    def test_carried_forward_when_omitted(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0, previous_close=188.0)
        u = cache.update("AAPL", 191.0)
        assert u.previous_close == 188.0
        assert u.previous_price == 190.0

    def test_can_be_overridden(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0, previous_close=188.0)
        u = cache.update("AAPL", 191.0, previous_close=190.5)
        assert u.previous_close == 190.5

    def test_not_carried_after_remove(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0, previous_close=188.0)
        cache.remove("AAPL")
        assert cache.update("AAPL", 191.0).previous_close is None

    def test_tickers_are_independent(self):
        cache = PriceCache()
        cache.update("AAPL", 190.0, previous_close=188.0)
        assert cache.update("MSFT", 400.0).previous_close is None


class _Minimal(MarketDataSource):
    async def start(self, tickers):
        pass

    async def stop(self):
        pass

    async def add_ticker(self, ticker):
        pass

    async def remove_ticker(self, ticker):
        pass

    def get_tickers(self):
        return []


class TestInterfaceDefaults:
    def test_error_hierarchy(self):
        assert issubclass(CapabilityError, MarketDataError)
        assert issubclass(UnknownTickerError, MarketDataError)

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            MarketDataSource()

    def test_metadata_defaults(self):
        s = _Minimal()
        assert s.name == "unknown"
        assert s.currency == "USD"

    async def test_is_supported_defaults_true(self):
        assert await _Minimal().is_supported("ANYTHING")

    async def test_optional_capabilities_raise(self):
        s = _Minimal()
        with pytest.raises(CapabilityError):
            await s.get_quotes(["AAPL"])
        with pytest.raises(CapabilityError):
            await s.get_daily_bars("AAPL", date(2026, 1, 1), date(2026, 1, 2))
        with pytest.raises(CapabilityError):
            await s.get_eod_closes(["AAPL"])
