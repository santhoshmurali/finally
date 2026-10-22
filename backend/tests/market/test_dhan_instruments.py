"""Instrument list parsing and download."""

import httpx
import pytest

from app.market.dhan.instruments import InstrumentResolver
from app.market.errors import DataUnavailableError, UnsupportedTickerError

CSV_TEXT = """EXCH_ID,SEGMENT,SECURITY_ID,INSTRUMENT,UNDERLYING_SYMBOL,SERIES
NSE,E,11536,EQUITY,TCS,EQ
NSE,E,2885,EQUITY,RELIANCE ,EQ
NSE,E,9999,EQUITY,JUNKBOND,SG
NSE,E,13,INDEX,NIFTY,EQ
NSE,E,500,EQUITY,M&M,EQ
"""


def test_only_equity_series_eq_rows_are_kept():
    resolver = InstrumentResolver.from_csv(CSV_TEXT)
    assert len(resolver) == 3
    assert "JUNKBOND" not in resolver and "NIFTY" not in resolver


def test_lookup_is_case_insensitive_and_trims_symbols():
    resolver = InstrumentResolver.from_csv(CSV_TEXT)
    assert resolver.security_id("reliance") == 2885
    assert resolver.security_id("M&M") == 500


def test_reverse_lookup():
    resolver = InstrumentResolver.from_csv(CSV_TEXT)
    assert resolver.ticker(11536) == "TCS"
    assert resolver.ticker(1) is None


def test_unknown_ticker_raises():
    with pytest.raises(UnsupportedTickerError):
        InstrumentResolver.from_csv(CSV_TEXT).security_id("AAPL")


async def test_download_follows_redirect():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.dhan.co":
            return httpx.Response(302, headers={"location": "https://s3.example/list.csv"})
        return httpx.Response(200, text=CSV_TEXT)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        resolver = await InstrumentResolver.download(http)
    assert resolver.security_id("TCS") == 11536


async def test_download_failure_is_data_unavailable():
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(DataUnavailableError):
            await InstrumentResolver.download(http)
