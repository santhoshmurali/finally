"""Tests for the simulator's seedable RNG, correlation groups, previous close and EOD API."""

import asyncio
from datetime import date, timedelta

import numpy as np
import pytest

from app.market.cache import PriceCache
from app.market.seed_prices import NSE_DEFAULTS, SEED_PRICES, US_DEFAULTS, derived_seed_price
from app.market.simulator import GBMSimulator, SimulatorDataSource
from app.market.synthetic_history import last_trading_day_before


class TestDerivedSeedPrice:
    def test_stable(self):
        assert derived_seed_price("PYPL") == derived_seed_price("PYPL")
        assert derived_seed_price("pypl") == derived_seed_price("PYPL")

    def test_in_range(self):
        for t in ("PYPL", "ZZZZ", "BRK.B", "M&M", "A"):
            assert 50.0 <= derived_seed_price(t) < 300.0

    def test_unknown_ticker_uses_derived_price(self):
        sim = GBMSimulator(["PYPL"])
        assert sim.get_price("PYPL") == derived_seed_price("PYPL")

    def test_same_price_across_simulators(self):
        assert GBMSimulator(["ZZZZ"]).get_price("ZZZZ") == GBMSimulator(["ZZZZ"]).get_price("ZZZZ")


class TestProfiles:
    def test_defaults_have_seed_prices(self):
        assert len(US_DEFAULTS) == len(NSE_DEFAULTS) == 10
        for t in US_DEFAULTS + NSE_DEFAULTS:
            assert SEED_PRICES[t] > 0

    def test_nse_tickers_simulate(self):
        sim = GBMSimulator(NSE_DEFAULTS)
        prices = sim.step()
        assert set(prices) == set(NSE_DEFAULTS)
        assert prices["TCS"] == pytest.approx(3900.0, rel=0.01)


class TestDeterminism:
    def test_same_rng_seed_same_path(self):
        a = GBMSimulator(["AAPL", "MSFT", "TSLA"], rng=np.random.default_rng(7))
        b = GBMSimulator(["AAPL", "MSFT", "TSLA"], rng=np.random.default_rng(7))
        for _ in range(200):
            assert a.step() == b.step()

    def test_different_seeds_differ(self):
        a = GBMSimulator(["AAPL", "MSFT"], rng=np.random.default_rng(1))
        b = GBMSimulator(["AAPL", "MSFT"], rng=np.random.default_rng(2))
        paths_a = [a.step() for _ in range(50)]
        paths_b = [b.step() for _ in range(50)]
        assert paths_a != paths_b

    def test_prices_stay_positive(self):
        sim = GBMSimulator(["TSLA", "NVDA"], event_probability=0.01, rng=np.random.default_rng(3))
        for _ in range(5000):
            assert all(p > 0 for p in sim.step().values())


class TestEvents:
    def test_events_always_fire_at_probability_one(self):
        sim = GBMSimulator(["AAPL"], event_probability=1.0, rng=np.random.default_rng(5))
        last = sim.get_price("AAPL")
        for _ in range(50):
            new = sim.step()["AAPL"]
            move = abs(new / last - 1)
            assert 0.018 <= move <= 0.052  # 2-5% shock (+ rounding)
            last = new

    def test_no_events_at_probability_zero(self):
        sim = GBMSimulator(["AAPL"], event_probability=0.0, rng=np.random.default_rng(5))
        last = sim.get_price("AAPL")
        for _ in range(500):
            new = sim.step()["AAPL"]
            assert abs(new / last - 1) < 0.005
            last = new


class TestCorrelation:
    @pytest.mark.parametrize(
        "a,b,expected",
        [
            ("AAPL", "MSFT", 0.6),
            ("JPM", "V", 0.5),
            ("TCS", "INFY", 0.65),
            ("HDFCBANK", "SBIN", 0.6),
            ("TSLA", "AAPL", 0.3),
            ("AAPL", "TSLA", 0.3),
            ("AAPL", "JPM", 0.3),
            ("TCS", "HDFCBANK", 0.3),
            ("ZZZZ", "AAPL", 0.3),
        ],
    )
    def test_pairwise(self, a, b, expected):
        assert GBMSimulator._pairwise_correlation(a, b) == expected

    def test_cholesky_reproduces_correlation_matrix(self):
        sim = GBMSimulator(["AAPL", "MSFT", "JPM"])
        recon = sim._cholesky @ sim._cholesky.T
        assert recon[0, 1] == pytest.approx(0.6)
        assert recon[0, 2] == pytest.approx(0.3)
        assert np.allclose(np.diag(recon), 1.0)

    def test_sampled_tech_pair_correlation(self):
        sim = GBMSimulator(["AAPL", "MSFT"], event_probability=0.0, rng=np.random.default_rng(11))
        rets = []
        for _ in range(4000):
            cur = sim._prices.copy()  # unrounded state
            sim.step()
            rets.append([np.log(sim._prices[t] / cur[t]) for t in ("AAPL", "MSFT")])
        corr = np.corrcoef(np.array(rets).T)[0, 1]
        assert corr == pytest.approx(0.6, abs=0.06)

    def test_non_positive_definite_matrix_is_shrunk(self, monkeypatch):
        real = np.linalg.cholesky
        calls = []

        def flaky(a):
            calls.append(1)
            if len(calls) < 3:
                raise np.linalg.LinAlgError("not PD")
            return real(a)

        monkeypatch.setattr(np.linalg, "cholesky", flaky)
        sim = GBMSimulator(["AAPL", "MSFT"])
        assert sim._cholesky is not None
        assert len(calls) == 3

    def test_falls_back_to_independent_moves(self, monkeypatch):
        def always_fail(a):
            raise np.linalg.LinAlgError("never PD")

        monkeypatch.setattr(np.linalg, "cholesky", always_fail)
        sim = GBMSimulator(["AAPL", "MSFT"])
        assert sim._cholesky is None
        assert set(sim.step()) == {"AAPL", "MSFT"}


class TestDtCoupling:
    async def test_dt_follows_update_interval(self):
        source = SimulatorDataSource(PriceCache(), update_interval=1.0)
        await source.start(["AAPL"])
        try:
            assert source._sim._dt == pytest.approx(1.0 / GBMSimulator.TRADING_SECONDS_PER_YEAR)
        finally:
            await source.stop()

    def test_larger_dt_gives_larger_moves(self):
        def spread(dt):
            sim = GBMSimulator(["AAPL"], dt=dt, event_probability=0.0, rng=np.random.default_rng(9))
            rets = []
            for _ in range(2000):
                cur = sim._prices["AAPL"]
                sim.step()
                rets.append(np.log(sim._prices["AAPL"] / cur))
            return np.std(rets)

        base = GBMSimulator.DEFAULT_DT
        assert spread(4 * base) == pytest.approx(2 * spread(base), rel=0.15)


class TestPreviousClose:
    async def test_first_update_has_previous_close_equal_to_seed(self):
        cache = PriceCache()
        source = SimulatorDataSource(cache, update_interval=10.0)
        await source.start(["AAPL", "TCS"])
        try:
            u = cache.get("AAPL")
            assert u.previous_close == 190.0
            assert u.price == 190.0
            assert u.day_change_percent == 0.0
            assert cache.get("TCS").previous_close == 3900.0
        finally:
            await source.stop()

    async def test_previous_close_persists_across_ticks(self):
        cache = PriceCache()
        source = SimulatorDataSource(cache, update_interval=0.01, event_probability=1.0, seed=1)
        await source.start(["AAPL"])
        try:
            await asyncio.sleep(0.1)
            u = cache.get("AAPL")
            assert u.previous_close == 190.0
            assert u.price != 190.0
            assert u.day_change_percent != 0.0
        finally:
            await source.stop()

    async def test_added_ticker_gets_previous_close(self):
        cache = PriceCache()
        source = SimulatorDataSource(cache, update_interval=10.0)
        await source.start(["AAPL"])
        try:
            await source.add_ticker("PYPL")
            assert cache.get("PYPL").previous_close == derived_seed_price("PYPL")
            await source.remove_ticker("PYPL")
            assert "PYPL" not in cache
            assert "PYPL" not in source._prev_close
        finally:
            await source.stop()


class TestSimulatorOnDemandApi:
    @pytest.fixture
    def source(self):
        return SimulatorDataSource(PriceCache(), update_interval=10.0)

    def test_metadata(self, source):
        assert source.name == "simulator"
        assert source.currency == "USD"

    @pytest.mark.parametrize("ticker", ["AAPL", "PYPL", "BRK.B", "M&M", "aapl", "TCS", "A"])
    async def test_supported(self, source, ticker):
        assert await source.is_supported(ticker)

    @pytest.mark.parametrize("ticker", ["", "AA PL", "???", "1ABC", "A" * 16, "AAPL;DROP"])
    async def test_unsupported(self, source, ticker):
        assert not await source.is_supported(ticker)

    async def test_quotes_for_streaming_ticker_come_from_cache(self, source):
        await source.start(["AAPL"])
        try:
            quotes = await source.get_quotes(["aapl"])
            assert quotes["AAPL"] == source._cache.get("AAPL")
        finally:
            await source.stop()

    async def test_quotes_for_non_streaming_ticker_use_seed_snapshot(self, source):
        quotes = await source.get_quotes(["MSFT", "PYPL", "???"])
        assert set(quotes) == {"MSFT", "PYPL"}
        assert quotes["MSFT"].price == 420.0
        assert quotes["MSFT"].previous_close == 420.0
        assert quotes["PYPL"].price == derived_seed_price("PYPL")

    async def test_quotes_do_not_write_cache(self, source):
        await source.get_quotes(["MSFT"])
        assert len(source._cache) == 0

    async def test_daily_bars_ascending_within_range(self, source):
        last = last_trading_day_before(date.today())
        start = last - timedelta(days=30)
        bars = await source.get_daily_bars("AAPL", start, date.today())
        assert bars
        assert all(start <= b.date <= date.today() for b in bars)
        assert [b.date for b in bars] == sorted(b.date for b in bars)
        assert all(b.date.weekday() < 5 for b in bars)
        assert bars[-1].date == last

    async def test_daily_bars_end_at_previous_close(self, source):
        """History ends exactly where today's live session starts."""
        bars = await source.get_daily_bars("AAPL", date(2000, 1, 1), date.today())
        assert bars[-1].close == 190.0

    async def test_daily_bars_end_at_live_previous_close_when_streaming(self, source):
        await source.start(["AAPL"])
        try:
            bars = await source.get_daily_bars("AAPL", date(2000, 1, 1), date.today())
            assert bars[-1].close == source._cache.get("AAPL").previous_close
        finally:
            await source.stop()

    async def test_daily_bars_stable_across_calls(self, source):
        a = await source.get_daily_bars("MSFT", date(2000, 1, 1), date.today())
        b = await source.get_daily_bars("MSFT", date(2000, 1, 1), date.today())
        assert a == b

    async def test_daily_bars_slice_consistent_with_full_series(self, source):
        full = await source.get_daily_bars("MSFT", date(2000, 1, 1), date.today())
        part = await source.get_daily_bars("MSFT", full[10].date, full[20].date)
        assert part == full[10:21]

    async def test_daily_bars_unsupported_ticker(self, source):
        assert await source.get_daily_bars("???", date(2000, 1, 1), date.today()) == []

    async def test_daily_bars_outside_lookback_are_empty(self, source):
        assert await source.get_daily_bars("AAPL", date(2000, 1, 1), date(2000, 12, 31)) == []

    async def test_eod_closes_default_is_previous_close(self, source):
        closes = await source.get_eod_closes(["aapl", "MSFT", "???"])
        assert closes == {"AAPL": 190.0, "MSFT": 420.0}

    async def test_eod_closes_on_specific_date(self, source):
        last = last_trading_day_before(date.today())
        day = last_trading_day_before(last)
        closes = await source.get_eod_closes(["AAPL"], on=day)
        bars = await source.get_daily_bars("AAPL", day, day)
        assert closes == {"AAPL": bars[0].close}

    async def test_eod_closes_with_no_data(self, source):
        assert await source.get_eod_closes(["AAPL"], on=date(2000, 1, 3)) == {}
