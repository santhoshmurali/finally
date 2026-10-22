"""Test doubles for the Dhan WebSocket and packet bytes."""

import asyncio
import inspect
import json
import struct


def ticker_bytes(security_id: int, price: float) -> bytes:
    return struct.pack("<BHBIfI", 2, 16, 1, security_id, price, 0)


def prev_close_bytes(security_id: int, price: float) -> bytes:
    return struct.pack("<BHBIfI", 6, 16, 1, security_id, price, 0)


def disconnect_bytes(code: int) -> bytes:
    return struct.pack("<BHBIH", 50, 10, 0, 0, code)


class FakeConnection:
    """Async-context-manager socket that replays a script.

    Script items: bytes are delivered as messages, exceptions are raised,
    callables (sync or async) are invoked, e.g. `feed.stop`.
    """

    def __init__(self, script: list) -> None:
        self.script = script
        self.sent: list[dict] = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self._messages()

    async def _messages(self):
        for item in self.script:
            if isinstance(item, Exception):
                raise item
            if callable(item):
                result = item()
                if inspect.isawaitable(result):
                    await result
                continue
            yield item
            await asyncio.sleep(0)


class FakeConnect:
    """Replacement for `websockets.connect`; each call consumes one session."""

    def __init__(self, *sessions) -> None:
        self.sessions = list(sessions)
        self.connections: list[FakeConnection] = []
        self.urls: list[str] = []

    def __call__(self, url: str):
        self.urls.append(url)
        session = self.sessions.pop(0)
        if isinstance(session, Exception):
            raise session
        connection = FakeConnection(session)
        self.connections.append(connection)
        return connection
