"""Attributed status frames and helpers for checksum-correct test variants."""

# Captured R-12100 response, mkeguy106/bmsmon BmsProtocolTest.kt,
# commit 4534382d00702e14199e2a2aaab50180cf0878ac.
REAL_STATUS = bytes.fromhex(
    "000065019355aa007c3300000c340000030d030d030d030d00000000000000000000000000000000000000000000000000000000170018000000000000001027102700000000000000000000000000000000000000000000000063006400000000000000000000008b"
)


def captured_status_frame() -> bytearray:
    return bytearray(REAL_STATUS)


def checksum_correct_status_frame(frame: bytearray) -> bytes:
    frame[-1] = sum(frame[:-1]) & 0xFF
    return bytes(frame)
