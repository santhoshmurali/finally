import pytest
from pydantic import ValidationError

from app.llm.schemas import LLMReply, LLMTrade


def test_full_reply_parses_from_json():
    raw = (
        '{"message": "Buying TCS", '
        '"trades": [{"ticker": "TCS", "quantity": 10, "side": "buy"}], '
        '"watchlist_changes": [{"ticker": "WIPRO", "action": "add"}]}'
    )
    reply = LLMReply.model_validate_json(raw)
    assert reply.message == "Buying TCS"
    assert reply.trades == [LLMTrade(ticker="TCS", quantity=10, side="buy")]
    assert reply.watchlist_changes[0].action == "add"


def test_trades_and_watchlist_default_to_empty():
    reply = LLMReply.model_validate_json('{"message": "Hello"}')
    assert reply.trades == []
    assert reply.watchlist_changes == []


@pytest.mark.parametrize("quantity", [0, -5])
def test_non_positive_trade_quantity_is_rejected(quantity):
    with pytest.raises(ValidationError):
        LLMTrade(ticker="TCS", quantity=quantity, side="buy")


def test_ticker_is_upper_cased():
    assert LLMTrade(ticker="tcs", quantity=1, side="buy").ticker == "TCS"


def test_unknown_side_is_rejected():
    with pytest.raises(ValidationError):
        LLMTrade(ticker="TCS", quantity=1, side="short")


def test_missing_message_is_rejected():
    with pytest.raises(ValidationError):
        LLMReply.model_validate_json('{"trades": []}')
