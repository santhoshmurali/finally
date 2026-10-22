"""Tests for deterministic synthetic daily bars."""

from datetime import date

from app.market.synthetic_history import (
    last_trading_day_before,
    synth_daily_bars,
    weekdays_ending_at,
)

END = date(2026, 10, 21)  # Wednesday


class TestCalendarHelpers:
    def test_weekdays_ending_at_skips_weekends(self):
        days = weekdays_ending_at(date(2026, 10, 19), 3)  # Monday
        assert days == [date(2026, 10, 15), date(2026, 10, 16), date(2026, 10, 19)]

    def test_weekdays_ending_on_weekend_rolls_back(self):
        assert weekdays_ending_at(date(2026, 10, 24), 1) == [date(2026, 10, 23)]  # Sat -> Fri

    def test_weekdays_count(self):
        days = weekdays_ending_at(END, 100)
        assert len(days) == 100
        assert all(d.weekday() < 5 for d in days)
        assert days == sorted(days)

    def test_last_trading_day_before(self):
        assert last_trading_day_before(date(2026, 10, 21)) == date(2026, 10, 20)  # Wed -> Tue
        assert last_trading_day_before(date(2026, 10, 19)) == date(2026, 10, 16)  # Mon -> Fri
        assert last_trading_day_before(date(2026, 10, 24)) == date(2026, 10, 23)  # Sat -> Fri
        assert last_trading_day_before(date(2026, 10, 25)) == date(2026, 10, 23)  # Sun -> Fri


class TestSynthDailyBars:
    def test_length_and_order(self):
        bars = synth_daily_bars("AAPL", END, 60, 190.0)
        assert len(bars) == 60
        assert [b.date for b in bars] == sorted(b.date for b in bars)
        assert bars[-1].date == END
        assert all(b.date.weekday() < 5 for b in bars)

    def test_last_close_equals_anchor(self):
        bars = synth_daily_bars("AAPL", END, 100, 190.0)
        assert bars[-1].close == 190.0

    def test_anchor_for_other_prices(self):
        for anchor in (12.34, 3900.0):
            assert synth_daily_bars("X", END, 30, anchor)[-1].close == anchor

    def test_deterministic(self):
        assert synth_daily_bars("TCS", END, 50, 3900.0) == synth_daily_bars("TCS", END, 50, 3900.0)

    def test_differs_between_tickers(self):
        a = synth_daily_bars("AAPL", END, 50, 100.0)
        b = synth_daily_bars("MSFT", END, 50, 100.0)
        assert [x.close for x in a] != [x.close for x in b]

    def test_ohlc_invariants(self):
        for bar in synth_daily_bars("TSLA", END, 365, 250.0, sigma=0.5):
            assert bar.high >= max(bar.open, bar.close) - 0.01
            assert bar.low <= min(bar.open, bar.close) + 0.01
            assert bar.low > 0
            assert bar.volume > 0

    def test_prices_positive_and_plausible(self):
        bars = synth_daily_bars("NVDA", END, 365, 800.0, mu=0.08, sigma=0.4)
        assert all(b.close > 0 for b in bars)

    def test_empty_for_non_positive_n(self):
        assert synth_daily_bars("AAPL", END, 0, 190.0) == []
        assert synth_daily_bars("AAPL", END, -5, 190.0) == []

    def test_single_bar(self):
        bars = synth_daily_bars("AAPL", END, 1, 190.0)
        assert len(bars) == 1
        assert bars[0].close == 190.0
