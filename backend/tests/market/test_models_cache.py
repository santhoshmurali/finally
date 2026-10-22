"""PriceUpdate and PriceCache behaviour."""

from app.market.cache import PriceCache
from app.market.models import PriceUpdate


def make(price, previous_price, previous_close):
    return PriceUpdate("TCS", price, previous_price, previous_close, 1.0)


def test_direction_and_changes():
    up = make(101.0, 100.0, 90.0)
    assert (up.direction, up.change) == ("up", 1.0)
    assert (make(99.0, 100.0, 90.0).direction) == "down"
    assert make(100.0, 100.0, 90.0).direction == "flat"


def test_day_change_uses_previous_close():
    update = make(110.0, 109.0, 100.0)
    assert update.day_change == 10.0
    assert update.day_change_percent == 10.0


def test_day_change_percent_zero_when_no_close():
    assert make(10.0, 10.0, 0.0).day_change_percent == 0.0


def test_to_dict_has_stream_fields():
    data = make(110.0, 109.0, 100.0).to_dict()
    assert data["ticker"] == "TCS"
    assert data["direction"] == "up"
    assert data["day_change_percent"] == 10.0


def test_first_update_is_its_own_previous_tick_and_close():
    update = PriceCache().update("TCS", 100.0)
    assert update.previous_price == 100.0
    assert update.previous_close == 100.0
    assert update.direction == "flat"


def test_second_update_tracks_previous_tick():
    cache = PriceCache()
    cache.update("TCS", 100.0)
    update = cache.update("TCS", 101.5)
    assert update.previous_price == 100.0
    assert update.direction == "up"


def test_previous_close_is_carried_forward():
    cache = PriceCache()
    cache.update("TCS", 100.0, previous_close=95.0)
    assert cache.update("TCS", 101.0).previous_close == 95.0


def test_set_previous_close_recomputes_cached_price():
    cache = PriceCache()
    cache.update("TCS", 100.0)
    cache.set_previous_close("TCS", 80.0)
    assert cache.get("TCS").day_change == 20.0


def test_set_previous_close_for_unknown_ticker_is_ignored():
    cache = PriceCache()
    cache.set_previous_close("NOPE", 1.0)
    assert len(cache) == 0


def test_version_increments_on_each_write():
    cache = PriceCache()
    cache.update("A", 1.0)
    cache.set_previous_close("A", 2.0)
    cache.remove("A")
    assert cache.version == 3
    cache.remove("A")
    assert cache.version == 3


def test_get_helpers_and_snapshot():
    cache = PriceCache()
    cache.update("A", 1.234)
    assert cache.get_price("A") == 1.23
    assert cache.get_price("B") is None
    assert "A" in cache and "B" not in cache
    snapshot = cache.get_all()
    cache.remove("A")
    assert "A" in snapshot
