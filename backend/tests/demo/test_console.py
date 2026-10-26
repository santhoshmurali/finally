"""The demo's state, the full-screen app driven by typed input, and the CLI paths."""

import asyncio
import base64
import json
import time

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from app.market import DEFAULT_WATCHLIST, PriceCache
from app.market.simulator import SimulatorDataSource
from demo.live_console import Demo, amain, load_env, parse_args, run_tui
from demo.render import Command, plain_text


@pytest.fixture
async def demo():
    cache = PriceCache()
    source = SimulatorDataSource(cache, update_interval=0.01, seed=1)
    demo = Demo(source, cache, window=10, interval=0.02)
    await demo.start(["TCS", "ITC"])
    yield demo
    await source.stop()


async def test_sampling_fills_the_chart_window(demo):
    for _ in range(3):
        demo.sample()
    assert len(demo.history.series("TCS")) == 3


async def test_fragments_show_status_and_symbols(demo):
    demo.sample()
    text = plain_text(demo.fragments())
    assert "SimulatorDataSource | feed OK | 2 symbols" in text
    assert "TCS" in text and "ITC" in text


async def test_add_and_remove_symbols(demo):
    assert not await demo.execute(Command("add", "WIPRO"))
    assert demo.symbols == ["TCS", "ITC", "WIPRO"] and "Added WIPRO" in demo.message
    await demo.execute(Command("remove", "ITC"))
    assert demo.symbols == ["TCS", "WIPRO"] and "ITC" not in demo.cache


async def test_duplicate_missing_and_invalid_symbols_only_set_a_message(demo):
    await demo.execute(Command("add", "TCS"))
    assert "already" in demo.message
    await demo.execute(Command("remove", "NOPE"))
    assert "not in the watchlist" in demo.message
    await demo.execute(Command("add", "-BAD"))
    assert "not a valid ticker" in demo.message
    await demo.execute(Command("error", "what"))
    assert "Unknown command" in demo.message
    assert demo.symbols == ["TCS", "ITC"]


async def test_quit_command(demo):
    assert await demo.execute(Command("quit"))


async def test_full_screen_app_accepts_typed_commands(demo):
    with create_pipe_input() as keys:
        run = asyncio.create_task(run_tui(demo, keys, DummyOutput()))
        await asyncio.sleep(0.2)
        keys.send_text("wipro\r")
        await asyncio.sleep(0.2)
        keys.send_text("rm itc\r")
        await asyncio.sleep(0.2)
        assert demo.symbols == ["TCS", "WIPRO"]
        keys.send_text("quit\r")
        await asyncio.wait_for(run, timeout=5)


async def test_ctrl_c_exits_the_app(demo):
    with create_pipe_input() as keys:
        run = asyncio.create_task(run_tui(demo, keys, DummyOutput()))
        await asyncio.sleep(0.2)
        keys.send_text("\x03")
        await asyncio.wait_for(run, timeout=5)


def test_load_env_reads_pairs_and_skips_comments(tmp_path):
    path = tmp_path / ".env"
    path.write_text('# c\n\nDHAN_ACESS_TOKEN = "abc"\nX=1=2\nbad line\n', encoding="utf-8")
    assert load_env(path) == {"DHAN_ACESS_TOKEN": '"abc"', "X": "1=2"}
    assert load_env(tmp_path / "missing") == {}


def test_parse_args_defaults():
    args = parse_args([])
    assert (args.window, args.interval, args.plain, args.simulator) == (40, 1.0, None, False)


async def test_headless_simulator_run_prints_the_default_watchlist(capsys):
    args = parse_args(["--simulator", "--plain", "0.3", "--interval", "0.1"])
    assert await amain(args) == 0
    out = capsys.readouterr().out
    assert all(symbol in out for symbol in DEFAULT_WATCHLIST)
    assert len(DEFAULT_WATCHLIST) == 10 and "SimulatorDataSource" in out


async def test_expired_token_stops_instead_of_simulating(tmp_path, capsys):
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    token = f"{part({})}.{part({'exp': time.time() - 5, 'dhanClientId': '1'})}.sig"
    env = tmp_path / ".env"
    env.write_text(f'DHAN_ACESS_TOKEN="{token}"\n', encoding="utf-8")
    assert await amain(parse_args(["--env", str(env), "--plain", "0.1"])) == 1
    out = capsys.readouterr().out
    assert "expired" in out and "--simulator" in out


async def test_wrong_terminal_gives_a_helpful_message(monkeypatch, capsys):
    from demo import live_console

    async def no_console(demo):
        raise live_console.NoConsoleScreenBufferError

    monkeypatch.setattr(live_console, "run_tui", no_console)
    assert await amain(parse_args(["--simulator"])) == 2
    assert "PowerShell" in capsys.readouterr().out
