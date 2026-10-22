"""Tests for the Dhan instrument resolver (offline)."""

import os
import time

import httpx
import pytest

from app.market.dhan.instruments import InstrumentResolver

HEADER = "EXCH_ID,SEGMENT,SECURITY_ID,INSTRUMENT,SERIES,UNDERLYING_SYMBOL,DISPLAY_NAME"
CSV_TEXT = "\n".join(
    [
        HEADER,
        "NSE,E,11536,EQUITY,EQ,TCS,Tata Consultancy Services",
        "NSE,E,2885,EQUITY,EQ, reliance ,Reliance Industries",
        "NSE,E,999,EQUITY,BE,TRADEFORTRADE,Trade For Trade",  # wrong series
        "NSE,E,13,INDEX,EQ,NIFTY,Nifty 50",  # not equity
        "BSE,E,500325,EQUITY,EQ,RELIANCE,Reliance BSE",  # wrong exchange
    ]
)


def make_resolver(tmp_path, handler=None, **kw) -> InstrumentResolver:
    http = None
    if handler is not None:
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    return InstrumentResolver(tmp_path, http=http, **kw)


class TestParsing:
    def test_keeps_only_nse_equity_eq(self, tmp_path):
        r = make_resolver(tmp_path)
        r.load_text(CSV_TEXT)

        assert len(r) == 2
        assert r.resolve("TCS").security_id == 11536
        assert r.resolve("TCS").name == "Tata Consultancy Services"
        assert r.resolve("TRADEFORTRADE") is None
        assert r.resolve("NIFTY") is None

    def test_symbols_are_stripped_and_uppercased(self, tmp_path):
        r = make_resolver(tmp_path)
        r.load_text(CSV_TEXT)
        inst = r.resolve("Reliance")
        assert inst is not None
        assert inst.ticker == "RELIANCE"
        assert inst.security_id == 2885  # NSE row wins; BSE row ignored
        assert inst.segment == "NSE_EQ"
        assert inst.instrument == "EQUITY"

    def test_by_key(self, tmp_path):
        r = make_resolver(tmp_path)
        r.load_text(CSV_TEXT)
        assert r.by_key("NSE_EQ", 11536).ticker == "TCS"
        assert r.by_key("NSE_EQ", 1) is None

    def test_unknown_ticker(self, tmp_path):
        r = make_resolver(tmp_path)
        r.load_text(CSV_TEXT)
        assert r.resolve("AAPL") is None

    def test_missing_columns_fail_loudly(self, tmp_path):
        r = make_resolver(tmp_path)
        with pytest.raises(RuntimeError, match="missing columns"):
            r.load_text("FOO,BAR\n1,2")

    def test_reload_replaces_previous_data(self, tmp_path):
        r = make_resolver(tmp_path)
        r.load_text(CSV_TEXT)
        r.load_text(HEADER + "\nNSE,E,1594,EQUITY,EQ,INFY,Infosys")
        assert r.resolve("TCS") is None
        assert r.resolve("INFY").security_id == 1594


class TestDownloadAndCache:
    async def test_downloads_and_writes_cache(self, tmp_path):
        calls = []

        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(200, text=CSV_TEXT)

        r = make_resolver(tmp_path, handler)
        await r.load()

        assert len(calls) == 1
        assert calls[0] == "https://api.dhan.co/v2/instrument/NSE_EQ"
        assert (tmp_path / "dhan-nse-eq-instruments.csv").read_text() == CSV_TEXT
        assert r.resolve("TCS") is not None

    async def test_follows_redirect(self, tmp_path):
        def handler(request):
            if request.url.host == "api.dhan.co":
                return httpx.Response(302, headers={"location": "https://s3.example/list.csv"})
            return httpx.Response(200, text=CSV_TEXT)

        r = make_resolver(tmp_path, handler)
        await r.load()
        assert r.resolve("TCS") is not None

    async def test_fresh_cache_skips_network(self, tmp_path):
        (tmp_path / "dhan-nse-eq-instruments.csv").write_text(CSV_TEXT)

        def handler(request):
            raise AssertionError("network should not be used")

        r = make_resolver(tmp_path, handler)
        await r.load()
        assert r.resolve("TCS") is not None

    async def test_stale_cache_is_refreshed(self, tmp_path):
        path = tmp_path / "dhan-nse-eq-instruments.csv"
        path.write_text(HEADER + "\nNSE,E,1594,EQUITY,EQ,INFY,Infosys")
        old = time.time() - 10 * 86_400
        os.utime(path, (old, old))

        r = make_resolver(tmp_path, lambda req: httpx.Response(200, text=CSV_TEXT))
        await r.load()

        assert r.resolve("TCS") is not None
        assert r.resolve("INFY") is None

    async def test_download_failure_uses_stale_cache(self, tmp_path):
        path = tmp_path / "dhan-nse-eq-instruments.csv"
        path.write_text(CSV_TEXT)
        old = time.time() - 10 * 86_400
        os.utime(path, (old, old))

        def handler(request):
            raise httpx.ConnectError("offline")

        r = make_resolver(tmp_path, handler)
        await r.load()
        assert r.resolve("TCS") is not None

    async def test_download_failure_without_cache_raises(self, tmp_path):
        r = make_resolver(tmp_path, lambda req: httpx.Response(500))
        with pytest.raises(httpx.HTTPError):
            await r.load()

    async def test_unwritable_cache_dir_is_tolerated(self, tmp_path):
        blocker = tmp_path / "file"
        blocker.write_text("x")  # a file where a directory is expected
        r = InstrumentResolver(
            blocker / "sub",
            http=httpx.AsyncClient(
                transport=httpx.MockTransport(lambda req: httpx.Response(200, text=CSV_TEXT))
            ),
        )
        await r.load()
        assert r.resolve("TCS") is not None
