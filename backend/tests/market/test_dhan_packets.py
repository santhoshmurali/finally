"""Binary packet decoding, including bytes captured from the live feed."""

import struct

from app.market.dhan.packets import Disconnect, PreviousClose, Tick, parse_packet

# Captured 2026-10-22 from wss://api-feed.dhan.co (TCS, NSE_EQ, security 11536).
LIVE_TICKER = bytes.fromhex("02100001102d000066ae1c45cc31da6a")
LIVE_PREV_CLOSE = bytes.fromhex("06100001102d000000101e4500000000")


def test_live_ticker_packet():
    assert parse_packet(LIVE_TICKER) == Tick("NSE_EQ", 11536, 2506.9)


def test_live_previous_close_packet():
    assert parse_packet(LIVE_PREV_CLOSE) == PreviousClose("NSE_EQ", 11536, 2529.0)


def test_disconnect_packet_carries_code():
    packet = struct.pack("<BHBIH", 50, 10, 0, 0, 807)
    assert parse_packet(packet) == Disconnect(807)


def test_unused_packet_types_are_ignored():
    assert parse_packet(struct.pack("<BHBIf", 5, 12, 1, 1, 0.0)) is None


def test_unknown_segment_code_is_kept_as_text():
    packet = struct.pack("<BHBIfI", 2, 16, 6, 1, 10.0, 0)
    assert parse_packet(packet).segment == "6"


def test_price_is_rounded_to_two_places():
    packet = struct.pack("<BHBIfI", 2, 16, 1, 1, 123.456789, 0)
    assert parse_packet(packet).price == 123.46
