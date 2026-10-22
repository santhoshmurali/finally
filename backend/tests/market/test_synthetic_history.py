"""Deterministic synthetic daily bars."""

from datetime import date

from app.market.synthetic_history import synthetic_bars

TODAY = date(2026, 10, 22)  # Thursday


def bars(**overrides):
    args = {"ticker": "TCS", "start": date(2026, 9, 1), "end": date(2026, 12, 31),
            "anchor_price": 2529.0, "today": TODAY}
    return synthetic_bars(**{**args, **overrides})


def test_last_bar_is_previous_session_and_closes_at_anchor():
    last = bars()[-1]
    assert last.day == date(2026, 10, 21)
    assert last.close == 2529.0


def test_today_and_future_are_excluded():
    assert all(b.day < TODAY for b in bars())


def test_weekends_are_skipped():
    assert all(b.day.weekday() < 5 for b in bars())


def test_is_deterministic():
    assert bars() == bars()


def test_overlapping_ranges_agree():
    wide = {b.day: b for b in bars()}
    narrow = bars(start=date(2026, 10, 5), end=date(2026, 10, 9))
    assert len(narrow) == 5
    assert all(wide[b.day] == b for b in narrow)


def test_different_tickers_differ():
    assert bars(ticker="INFY")[-5:] != bars()[-5:]


def test_ohlc_is_consistent():
    for b in bars():
        assert b.low <= min(b.open, b.close) and b.high >= max(b.open, b.close)
        assert b.volume > 0


def test_monday_anchor_is_previous_friday():
    assert bars(today=date(2026, 10, 26))[-1].day == date(2026, 10, 23)


def test_empty_when_range_is_all_future():
    assert bars(start=date(2026, 11, 1), end=date(2026, 11, 30)) == []
