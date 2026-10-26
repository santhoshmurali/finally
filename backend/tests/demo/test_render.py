"""Pure rendering helpers of the console demo."""

import pytest

from app.market.models import PriceUpdate
from demo.render import (
    BLOCKS,
    Command,
    PriceHistory,
    build_rows,
    parse_command,
    plain_text,
    sparkline,
    table_fragments,
)


def test_sparkline_of_nothing_is_blank_of_full_width():
    assert sparkline([], 10) == " " * 10


def test_sparkline_right_aligns_short_history():
    line = sparkline([100.0, 101.0], 6)
    assert len(line) == 6 and line[:4] == "    "


def test_sparkline_keeps_only_the_last_window():
    assert len(sparkline(list(range(1, 100)), 10)) == 10


def test_sparkline_spans_lowest_to_highest_block_for_a_real_move():
    line = sparkline([100.0, 105.0, 110.0], 3)
    assert line[0] == BLOCKS[0] and line[-1] == BLOCKS[-1]


def test_sparkline_rises_and_falls_with_price():
    up = sparkline([1.0, 2.0, 3.0, 4.0], 4)
    assert list(up) == sorted(up)
    down = sparkline([4.0, 3.0, 2.0, 1.0], 4)
    assert list(down) == sorted(down, reverse=True)


def test_sparkline_is_flat_for_constant_prices():
    assert len(set(sparkline([257.5] * 8, 8))) == 1


def test_sparkline_does_not_exaggerate_a_one_tick_wiggle():
    line = sparkline([100.00, 100.01], 2)
    assert BLOCKS[0] not in line and BLOCKS[-1] not in line


def test_history_keeps_a_fixed_window_per_symbol():
    history = PriceHistory(3)
    for price in (1.0, 2.0, 3.0, 4.0):
        history.sample({"TCS": price})
    assert history.series("TCS") == [2.0, 3.0, 4.0]
    assert history.series("NOPE") == []


def test_history_drop():
    history = PriceHistory(3)
    history.sample({"TCS": 1.0})
    history.drop("TCS")
    history.drop("TCS")
    assert history.series("TCS") == []


def make_prices():
    return {"TCS": PriceUpdate("TCS", 2521.5, 2520.0, 2530.0, 1792690207.0)}


def test_build_rows_for_priced_and_waiting_symbols():
    history = PriceHistory(5)
    history.sample({"TCS": 2520.0})
    history.sample({"TCS": 2521.5})
    tcs, wait = build_rows(["TCS", "INFY"], make_prices(), history, 5)
    assert (tcs.price, tcs.direction, tcs.trend_up) == (2521.5, "up", True)
    assert tcs.day_percent == pytest.approx(-0.3359, abs=0.001)
    assert wait.price is None and wait.chart == " " * 5


def test_build_rows_trend_is_down_when_window_ends_lower():
    history = PriceHistory(5)
    history.sample({"TCS": 2530.0})
    history.sample({"TCS": 2521.5})
    assert not build_rows(["TCS"], make_prices(), history, 5)[0].trend_up


def test_table_shows_symbol_price_percent_and_waiting_state():
    history = PriceHistory(5)
    history.sample({"TCS": 2521.5})
    rows = build_rows(["TCS", "INFY"], make_prices(), history, 5)
    text = plain_text(table_fragments(rows, 5, 40))
    assert "SYMBOL" in text and "LTP" in text and "CHG %" in text and "last 40s" in text
    tcs_line = next(line for line in text.splitlines() if "TCS" in line)
    assert "2,521.50" in tcs_line and "▼ -0.34%" in tcs_line
    assert "waiting for first tick" in next(line for line in text.splitlines() if "INFY" in line)


def test_positive_change_uses_up_arrow_and_green_style():
    prices = {"ITC": PriceUpdate("ITC", 260.0, 259.0, 250.0, 1792690207.0)}
    fragments = table_fragments(build_rows(["ITC"], prices, PriceHistory(3), 3), 3, 3)
    assert any(style == "class:up" and "▲ +4.00%" in text for style, text in fragments)


@pytest.mark.parametrize(("text", "expected"), [
    ("", None),
    ("   ", None),
    ("tcs", Command("add", "TCS")),
    ("add wipro", Command("add", "WIPRO")),
    ("A m&m", Command("add", "M&M")),
    ("rm itc", Command("remove", "ITC")),
    ("remove ITC", Command("remove", "ITC")),
    ("del itc", Command("remove", "ITC")),
    ("quit", Command("quit")),
    ("Q", Command("quit")),
    ("exit", Command("quit")),
    ("rm", Command("error", "rm")),
    ("add a b", Command("error", "add a b")),
])
def test_parse_command(text, expected):
    assert parse_command(text) == expected
