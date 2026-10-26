"""Live console demo: a streaming watchlist table with a line chart per symbol.

Run from `backend/`:  uv run --group demo python -m demo
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    BufferControl,
    FormattedTextControl,
    HSplit,
    Layout,
    VSplit,
    Window,
)
from prompt_toolkit.output import Output
from prompt_toolkit.styles import Style

from app.market import (
    DEFAULT_WATCHLIST,
    MarketDataError,
    MarketDataSource,
    PriceCache,
    create_market_source,
)

from .render import (
    Command,
    Fragments,
    PriceHistory,
    build_rows,
    parse_command,
    plain_text,
    table_fragments,
)

try:
    from prompt_toolkit.output.win32 import NoConsoleScreenBufferError
except (ImportError, OSError, AttributeError):  # not Windows
    class NoConsoleScreenBufferError(Exception):
        """Placeholder so the except clause below is valid on every platform."""

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
HELP = "Type a symbol to add it | rm SYMBOL to remove | quit to exit"
STYLE = Style.from_dict({
    "header": "bold reverse",
    "up": "ansigreen",
    "down": "ansired",
    "tick-up": "bold ansigreen",
    "tick-down": "bold ansired",
    "dim": "ansibrightblack",
    "status": "ansicyan",
})


def load_env(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE reader for the project `.env` (quotes are handled downstream)."""
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


class Demo:
    """Watchlist state shared by the full-screen and headless runners."""

    def __init__(self, source: MarketDataSource, cache: PriceCache, window: int,
                 interval: float) -> None:
        self.source = source
        self.cache = cache
        self.window = window
        self.interval = interval
        self.symbols: list[str] = []
        self.history = PriceHistory(window)
        self.message = HELP

    async def start(self, symbols: list[str]) -> None:
        await self.source.start(symbols)
        self.symbols = list(symbols)

    def sample(self) -> None:
        """Record the latest price of each symbol as the next chart point."""
        prices = self.cache.get_all()
        self.history.sample({s: prices[s].price for s in self.symbols if s in prices})

    async def run_sampler(self) -> None:
        while True:
            self.sample()
            await asyncio.sleep(self.interval)

    def fragments(self) -> Fragments:
        rows = build_rows(self.symbols, self.cache.get_all(), self.history, self.window)
        feed = "OK" if self.source.healthy() else "DOWN"
        status = (f" {type(self.source).__name__} | feed {feed} | {len(self.symbols)} symbols | "
                  f"{datetime.now():%H:%M:%S}\n")
        return [
            *table_fragments(rows, self.window, self.window * self.interval),
            ("", "\n"), ("class:status", status), ("class:dim", f" {self.message}\n"),
        ]

    async def execute(self, command: Command) -> bool:
        """Apply a command. Returns True when the user asked to quit."""
        if command.action == "quit":
            return True
        if command.action == "error":
            self.message = f"Unknown command: {command.symbol!r}. {HELP}"
        elif command.action == "add":
            await self._add(command.symbol)
        else:
            await self._remove(command.symbol)
        return False

    async def _add(self, symbol: str) -> None:
        if symbol in self.symbols:
            self.message = f"{symbol} is already in the watchlist"
            return
        try:
            await self.source.add_ticker(symbol)
        except MarketDataError as exc:
            self.message = str(exc)
            return
        self.symbols.append(symbol)
        self.message = f"Added {symbol}"

    async def _remove(self, symbol: str) -> None:
        if symbol not in self.symbols:
            self.message = f"{symbol} is not in the watchlist"
            return
        await self.source.remove_ticker(symbol)
        self.symbols.remove(symbol)
        self.history.drop(symbol)
        self.message = f"Removed {symbol}"


def build_app(demo: Demo, input: Input | None = None, output: Output | None = None) -> Application:
    """Full-screen layout: live table on top, command line at the bottom."""
    buffer = Buffer(multiline=False)
    pending: set[asyncio.Task] = set()

    async def handle(command: Command) -> None:
        if await demo.execute(command):
            app.exit()

    def on_accept(_: Buffer) -> bool:
        command = parse_command(buffer.text)
        if command is not None:
            task = asyncio.ensure_future(handle(command))
            pending.add(task)
            task.add_done_callback(pending.discard)
        return False

    buffer.accept_handler = on_accept
    prompt_input = Window(BufferControl(buffer))
    root = HSplit([
        Window(FormattedTextControl(demo.fragments), wrap_lines=False),
        Window(height=1, char="─", style="class:dim"),
        VSplit([Window(FormattedTextControl("> "), width=2, dont_extend_width=True), prompt_input],
               height=1),
    ])
    keys = KeyBindings()

    @keys.add("c-c")
    @keys.add("c-d")
    def _(event) -> None:
        event.app.exit()

    app = Application(layout=Layout(root, focused_element=prompt_input), key_bindings=keys,
                      style=STYLE, full_screen=True, refresh_interval=0.5,
                      input=input, output=output)
    return app


async def run_tui(demo: Demo, input: Input | None = None, output: Output | None = None) -> None:
    sampler = asyncio.create_task(demo.run_sampler())
    try:
        await build_app(demo, input, output).run_async()
    finally:
        sampler.cancel()


async def run_plain(demo: Demo, seconds: float) -> None:
    """Headless mode: print the table every interval, then stop (for logs and checks)."""
    loop = asyncio.get_running_loop()
    end = loop.time() + seconds
    while loop.time() < end:
        demo.sample()
        print(plain_text(demo.fragments()), flush=True)
        await asyncio.sleep(demo.interval)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="demo", description="Live NSE watchlist in the console")
    parser.add_argument("--simulator", action="store_true",
                        help="use the built-in simulator instead of Dhan live data")
    parser.add_argument("--window", type=int, default=40, help="chart width in samples")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds per chart sample")
    parser.add_argument("--plain", type=float, metavar="SECONDS",
                        help="no full-screen UI: print the table for SECONDS, then exit")
    parser.add_argument("--env", type=Path, default=ENV_PATH, help="path of the .env file")
    return parser.parse_args(argv)


async def amain(args: argparse.Namespace) -> int:
    cache = PriceCache()
    try:
        source = create_market_source(cache, {} if args.simulator else load_env(args.env))
        demo = Demo(source, cache, args.window, args.interval)
        print(f"Starting {type(source).__name__} ...", flush=True)
        await demo.start(DEFAULT_WATCHLIST)
    except MarketDataError as exc:
        print(f"Cannot start live data: {exc}\nGenerate a new Dhan token, or use --simulator.")
        return 1
    try:
        await (run_plain(demo, args.plain) if args.plain else run_tui(demo))
    except NoConsoleScreenBufferError:
        print("The full-screen view needs a real console: run it in PowerShell, cmd or "
              "Windows Terminal (not Git Bash), or add --plain 10 for a text-only printout.")
        return 2
    finally:
        await source.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(amain(parse_args(argv)))
