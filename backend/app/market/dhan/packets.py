"""Decoder for Dhan Live Market Feed binary packets (little-endian)."""

from __future__ import annotations

import struct
from dataclasses import dataclass

TICKER_CODE = 2
PREV_CLOSE_CODE = 6
DISCONNECT_CODE = 50

_HEADER_FORMAT = "<BHBI"
_TICKER_FORMAT = "<BHBIfI"
_DISCONNECT_FORMAT = "<BHBIH"

SEGMENT_NAMES = {
    0: "IDX_I", 1: "NSE_EQ", 2: "NSE_FNO", 3: "NSE_CURRENCY",
    4: "BSE_EQ", 5: "MCX_COMM", 7: "BSE_CURRENCY", 8: "BSE_FNO",
}


@dataclass(frozen=True, slots=True)
class Tick:
    """Last traded price of an instrument."""

    segment: str
    security_id: int
    price: float


@dataclass(frozen=True, slots=True)
class PreviousClose:
    """Previous session close of an instrument."""

    segment: str
    security_id: int
    price: float


@dataclass(frozen=True, slots=True)
class Disconnect:
    """Server-initiated disconnect with a Dhan error code (805-809)."""

    code: int


Packet = Tick | PreviousClose | Disconnect


def parse_packet(buf: bytes) -> Packet | None:
    """Decode one packet; return None for types FinAlly does not use.

    The exchange timestamp inside ticker packets is deliberately ignored: Dhan
    encodes IST wall-clock time as if it were UTC, so consumers stamp ticks
    with their own receive time instead.
    """
    code = buf[0]
    if code == TICKER_CODE:
        _, _, segment, security_id, price, _ = struct.unpack(_TICKER_FORMAT, buf[:16])
        return Tick(SEGMENT_NAMES.get(segment, str(segment)), security_id, round(price, 2))
    if code == PREV_CLOSE_CODE:
        _, _, segment, security_id, price, _ = struct.unpack(_TICKER_FORMAT, buf[:16])
        return PreviousClose(SEGMENT_NAMES.get(segment, str(segment)), security_id, round(price, 2))
    if code == DISCONNECT_CODE:
        return Disconnect(struct.unpack(_DISCONNECT_FORMAT, buf[:10])[4])
    return None
