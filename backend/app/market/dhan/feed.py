"""Dhan Live Market Feed: one WebSocket, ticker subscriptions, reconnect with backoff."""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
from collections.abc import Callable

import websockets

from ..errors import AuthenticationError
from .auth import Credentials
from .instruments import SEGMENT
from .packets import Disconnect, Packet, parse_packet

logger = logging.getLogger(__name__)

FEED_URL = "wss://api-feed.dhan.co?version=2&token={token}&clientId={client_id}&authType=2"
SUBSCRIBE_TICKER = 15
UNSUBSCRIBE_TICKER = 16
MAX_INSTRUMENTS_PER_MESSAGE = 100
AUTH_DISCONNECT_CODES = {806, 807, 808, 809}
UNHEALTHY_AFTER_FAILURES = 3


class DhanFeed:
    """Streams ticker and previous-close packets of NSE equities to `on_packet`.

    Subscribing a ticker yields its last price and previous close immediately,
    even when the market is closed. `run()` returns only after `stop()` or a
    fatal authentication problem, which is then available as `error`.
    """

    def __init__(
        self,
        credentials: Credentials,
        on_packet: Callable[[Packet], None],
        connect=websockets.connect,
        max_backoff: float = 30.0,
    ) -> None:
        self._credentials = credentials
        self._on_packet = on_packet
        self._connect = connect
        self._max_backoff = max_backoff
        self._security_ids: set[int] = set()
        self._ws = None
        self._stopping = False
        self._failures = 0
        self._received = False
        self.error: AuthenticationError | None = None

    @property
    def healthy(self) -> bool:
        """False after a fatal auth error or repeated connection failures."""
        return self.error is None and self._failures < UNHEALTHY_AFTER_FAILURES

    async def subscribe(self, security_ids: list[int]) -> None:
        """Track `security_ids`; send now if connected, else on the next connect."""
        new_ids = [i for i in security_ids if i not in self._security_ids]
        self._security_ids.update(new_ids)
        if self._ws is not None:
            await self._send(SUBSCRIBE_TICKER, new_ids)

    async def unsubscribe(self, security_ids: list[int]) -> None:
        """Stop tracking `security_ids`."""
        known = [i for i in security_ids if i in self._security_ids]
        self._security_ids.difference_update(known)
        if self._ws is not None:
            await self._send(UNSUBSCRIBE_TICKER, known)

    async def run(self) -> None:
        """Connect, stream, and reconnect until stopped or authentication fails."""
        backoff = 1.0
        while not self._stopping and self.error is None:
            if self._credentials.expires_at <= time.time():
                self.error = AuthenticationError("Dhan access token expired while streaming")
                break
            received = await self._stream_once()
            if self._stopping or self.error is not None:
                break
            self._failures = 0 if received else self._failures + 1
            backoff = 1.0 if received else min(backoff * 2, self._max_backoff)
            await asyncio.sleep(backoff)

    async def stop(self) -> None:
        """End `run()` and close the socket."""
        self._stopping = True
        if self._ws is not None:
            await self._ws.close()

    async def _stream_once(self) -> bool:
        """One connection lifetime. Returns True if any packet arrived."""
        url = FEED_URL.format(token=self._credentials.token, client_id=self._credentials.client_id)
        self._received = False
        try:
            async with self._connect(url) as ws:
                self._ws = ws
                await self._send(SUBSCRIBE_TICKER, sorted(self._security_ids))
                async for message in ws:
                    if isinstance(message, bytes) and self._handle(message):
                        break
        except (websockets.WebSocketException, OSError) as exc:
            logger.warning("Dhan feed connection lost: %s", type(exc).__name__)
        finally:
            self._ws = None
        return self._received

    def _handle(self, message: bytes) -> bool:
        """Dispatch one packet. Returns True when the connection must end.

        Only real data counts as `received`; a server disconnect does not, so
        repeated disconnects keep backing off and turn the feed unhealthy.
        """
        try:
            packet = parse_packet(message)
        except (IndexError, struct.error):
            logger.warning("Dhan feed sent an undecodable packet (%d bytes)", len(message))
            return False
        if isinstance(packet, Disconnect):
            if packet.code in AUTH_DISCONNECT_CODES:
                self.error = AuthenticationError(
                    f"Dhan feed rejected the session (code {packet.code})"
                )
                return True
            logger.warning("Dhan feed disconnect code %s", packet.code)
            return True
        self._received = True
        if packet is not None:
            try:
                self._on_packet(packet)
            except Exception:
                logger.exception("Dhan feed packet handler failed")
        return False

    async def _send(self, request_code: int, security_ids: list[int]) -> None:
        """Send subscribe/unsubscribe messages in batches the API accepts.

        A socket that just dropped is ignored: the tracked ids are resubscribed
        on the next connect.
        """
        for i in range(0, len(security_ids), MAX_INSTRUMENTS_PER_MESSAGE):
            batch = security_ids[i : i + MAX_INSTRUMENTS_PER_MESSAGE]
            message = {
                "RequestCode": request_code,
                "InstrumentCount": len(batch),
                "InstrumentList": [
                    {"ExchangeSegment": SEGMENT, "SecurityId": str(security_id)}
                    for security_id in batch
                ],
            }
            try:
                await self._ws.send(json.dumps(message))
            except websockets.ConnectionClosed:
                return
