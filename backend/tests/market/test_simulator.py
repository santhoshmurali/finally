"""GBMSimulator maths and SimulatorDataSource behaviour."""

import asyncio
from datetime import date

import numpy as np
import pytest

from app.market import simulator as simulator_module
from app.market.cache import PriceCache
from app.market.errors import UnsupportedTickerError
from app.market.seed_prices import DEFAULT_WATCHLIST, SEED_PRICES, seed_price_for
from app.market.simulator import GBMSimulator, SimulatorDataSource


def test_starts_at_seed_prices():
    sim = GBMSimulator(DEFAULT_WATCHLIST, seed=1)
    assert sim.step().keys() == set(DEFAULT_WATCHLIST)
    assert sim.add_ticker("TCS") == pytest.approx(SEED_PRICES["TCS"], rel=0.01)


def test_same_seed_gives_same_path():
    a, b = GBMSimulator(["TCS", "INFY"], seed=7), GBMSimulator(["TCS", "INFY"], seed=7)
    assert [a.step() for _ in range(20)] == [b.step() for _ in range(20)]


def test_different_seed_gives_different_path():
    a, b = GBMSimulator(["TCS"], seed=1), GBMSimulator(["TCS"], seed=2)
    assert [a.step() for _ in range(5)] != [b.step() for _ in range(5)]


def test_prices_stay_positive_over_a_long_run():
    sim = GBMSimulator(DEFAULT_WATCHLIST, seed=3)
    for _ in range(5000):
        prices = sim.step()
    assert all(p > 0 for p in prices.values())


def test_gbm_log_return_statistics():
    """Without events, per-step log returns have std sigma*sqrt(dt)."""
    simulator_module.EVENT_PROBABILITY, saved = 0.0, simulator_module.EVENT_PROBABILITY
    try:
        sim = GBMSimulator(["ITC"], dt=1e-5, seed=11)
        prices = [SEED_PRICES["ITC"]] + [sim.step()["ITC"] for _ in range(20000)]
    finally:
        simulator_module.EVENT_PROBABILITY = saved
    returns = np.diff(np.log(prices))
    assert returns.std() == pytest.approx(0.19 * np.sqrt(1e-5), rel=0.08)


def test_group_members_are_more_correlated_than_strangers():
    simulator_module.EVENT_PROBABILITY, saved = 0.0, simulator_module.EVENT_PROBABILITY
    try:
        sim = GBMSimulator(["TCS", "INFY", "ITC"], dt=1e-5, seed=5)
        series = np.array([list(sim.step().values()) for _ in range(8000)])
    finally:
        simulator_module.EVENT_PROBABILITY = saved
    r = np.diff(np.log(series), axis=0)
    same_group = np.corrcoef(r[:, 0], r[:, 1])[0, 1]
    different_group = np.corrcoef(r[:, 0], r[:, 2])[0, 1]
    assert same_group == pytest.approx(0.6, abs=0.06)
    assert different_group == pytest.approx(0.3, abs=0.06)


def test_events_produce_2_to_5_percent_jumps(monkeypatch):
    monkeypatch.setattr(simulator_module, "EVENT_PROBABILITY", 1.0)
    sim = GBMSimulator(["ITC"], dt=1e-12, seed=4)
    for _ in range(20):
        before = sim._prices["ITC"]
        after = sim.step()["ITC"]
        assert 0.0199 <= abs(after / before - 1) <= 0.0501


def test_add_and_remove_tickers():
    sim = GBMSimulator(["TCS"], seed=1)
    sim.add_ticker("INFY")
    sim.add_ticker("INFY")
    assert sorted(sim.tickers) == ["INFY", "TCS"]
    sim.remove_ticker("TCS")
    sim.remove_ticker("TCS")
    assert sim.tickers == ["INFY"]
    sim.remove_ticker("INFY")
    assert sim.step() == {}


def test_unknown_ticker_seed_is_stable_and_in_range():
    assert seed_price_for("ZOMATO") == seed_price_for("ZOMATO")
    assert 100.0 <= seed_price_for("ZOMATO") <= 3000.0
    assert seed_price_for("ZOMATO") != seed_price_for("PAYTM")


async def test_source_seeds_cache_with_previous_close():
    cache = PriceCache()
    source = SimulatorDataSource(cache, update_interval=10, seed=1)
    await source.start(["TCS", "m&m"])
    assert cache.get("TCS").price == 2529.0
    assert cache.get("TCS").previous_close == 2529.0
    assert source.get_tickers() == ["M&M", "TCS"]
    await source.stop()


async def test_source_updates_cache_over_time():
    cache = PriceCache()
    source = SimulatorDataSource(cache, update_interval=0.01, seed=1)
    await source.start(["TCS"])
    await asyncio.sleep(0.1)
    assert cache.version > 1
    assert cache.get("TCS").previous_close == 2529.0
    assert source.healthy()
    await source.stop()
    assert not source.healthy()


async def test_source_add_and_remove_ticker():
    cache = PriceCache()
    source = SimulatorDataSource(cache, update_interval=10, seed=1)
    await source.start(["TCS"])
    await source.add_ticker("wipro")
    await source.add_ticker("WIPRO")
    assert "WIPRO" in cache and source.get_tickers() == ["TCS", "WIPRO"]
    await source.remove_ticker("wipro")
    assert "WIPRO" not in cache and source.get_tickers() == ["TCS"]
    await source.stop()


@pytest.mark.parametrize("bad", ["", "AA PL", "<script>", "X" * 25, "-TCS"])
async def test_source_rejects_invalid_symbols(bad):
    source = SimulatorDataSource(PriceCache(), update_interval=10)
    await source.start(["TCS"])
    with pytest.raises(UnsupportedTickerError):
        await source.add_ticker(bad)
    await source.stop()


async def test_source_start_rejects_invalid_symbol():
    with pytest.raises(UnsupportedTickerError):
        await SimulatorDataSource(PriceCache()).start(["TCS", "bad symbol"])


async def test_source_daily_bars_end_at_previous_close():
    source = SimulatorDataSource(PriceCache(), update_interval=10)
    await source.start(["TCS"])
    bars = await source.daily_bars("TCS", date(2020, 1, 1), date(2100, 1, 1))
    assert bars[-1].close == 2529.0
    assert bars[-1].day < date.today()
    await source.stop()


async def test_stop_before_start_is_safe():
    await SimulatorDataSource(PriceCache()).stop()
