"""BMS BLE driver for Redodo/LiTime LiFePO4 batteries.

Implements:
  - BatteryTelemetry dataclass
  - parse_bms_payload() — pure parser, no I/O, fully unit-testable
  - poll_battery()     — async BleakClient single-poll lifecycle
"""

from __future__ import annotations

import asyncio
import logging
import struct
import time
from dataclasses import dataclass
from typing import Literal
from bleak.backends.device import BLEDevice

logger = logging.getLogger(__name__)

TX_NOTIFY_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
RX_WRITE_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"
REQUEST_PAYLOAD: bytes = bytes([0x00, 0x00, 0x04, 0x01, 0x13, 0x55, 0xAA, 0x17])
MIN_PAYLOAD_LEN = 101  # Fields through byte 99 plus a trailing checksum.
MAX_RESPONSE_BYTES = 512
STATUS_HEADER = b"\x00\x00"
STATUS_MARKER = b"\x01\x93\x55\xaa"
BmsState = Literal["idle", "charging", "discharging", "disabled", "unknown"]
SocSource = Literal["bms", "capacity"]
PROTECTION_FLAGS: tuple[tuple[int, str], ...] = (
    (0x04, "Overcharge"), (0x20, "Over-discharge"),
    (0x40, "Charging overcurrent"), (0x80, "Discharging overcurrent"),
    (0x100, "High temperature while charging"),
    (0x200, "High temperature while discharging"),
    (0x400, "Low temperature while charging"),
    (0x800, "Low temperature while discharging"),
    (0x4000, "Short circuit"),
)


def _frame_start(data: bytes | bytearray) -> int | None:
    marker = data.find(STATUS_MARKER, 3)
    while marker >= 0:
        start = marker - 3
        if data[start:start + 2] == STATUS_HEADER:
            return start
        marker = data.find(STATUS_MARKER, marker + 1)
    return None


def expected_response_length(data: bytes | bytearray) -> int | None:
    """Return buffer length needed for the realigned, declared status frame."""
    start = _frame_start(data)
    return None if start is None else start + data[start + 2] + 4


def _validated_frame(data: bytes) -> bytes:
    if len(data) < MIN_PAYLOAD_LEN:
        raise ValueError("Payload too short for status fields")
    start = _frame_start(data)
    if start is None:
        raise ValueError("Invalid status response header")
    length = data[start + 2] + 4
    if length < MIN_PAYLOAD_LEN:
        raise ValueError("Declared status length does not cover required fields")
    if len(data) < start + length:
        raise ValueError("Incomplete status response")
    frame = data[start:start + length]
    # Upstream's captured 105-byte frame ends in 0x8b = sum(frame[:-1]) & 0xff.
    if sum(frame[:-1]) & 0xff != frame[-1]:
        raise ValueError("Invalid status response checksum")
    return frame


@dataclass(frozen=True, slots=True)
class BatteryTelemetry:
    timestamp: float
    voltage_v: float
    current_a: float
    power_w: float
    soc_percent: float
    remaining_ah: float
    capacity_ah: float
    cell_temp_c: int
    bms_temp_c: int
    cell_voltages_v: tuple[float, ...]
    reported_soc_percent: float | None
    soc_source: SocSource
    soh_percent: float | None
    cycle_count: int
    bms_state_raw: int
    bms_state: BmsState
    protection_flags: int
    active_protections: tuple[str, ...]


def parse_bms_payload(data: bytes, timestamp: float | None = None) -> BatteryTelemetry:
    """Validate and parse a complete little-endian status response."""
    data = _validated_frame(data)

    voltage_mv: int = struct.unpack_from("<H", data, 12)[0]
    voltage_v = round(voltage_mv / 1000.0, 3)

    raw_cells: tuple[int, ...] = struct.unpack_from("<16H", data, 16)
    cell_voltages_v = tuple(round(c / 1000.0, 3) for c in raw_cells if c > 0)

    current_ma: int = struct.unpack_from("<i", data, 48)[0]
    current_a = round(current_ma / 1000.0, 3)

    cell_temp_c: int = struct.unpack_from("<h", data, 52)[0]
    bms_temp_c: int = struct.unpack_from("<h", data, 54)[0]

    remaining_raw: int = struct.unpack_from("<H", data, 62)[0]
    remaining_ah = round(remaining_raw / 100.0, 2)

    capacity_raw: int = struct.unpack_from("<I", data, 64)[0]
    capacity_ah = round(capacity_raw / 100.0, 2)

    power_w = round(voltage_v * current_a, 2)
    soc_percent = (
        0.0
        if capacity_ah <= 0
        else min(100.0, max(0.0, round((remaining_ah / capacity_ah) * 100.0, 1)))
    )

    reported_soc_raw = struct.unpack_from("<H", data, 90)[0]
    reported_soc = float(reported_soc_raw) if reported_soc_raw <= 100 else None
    soh_raw = struct.unpack_from("<I", data, 92)[0]
    state_raw = struct.unpack_from("<H", data, 88)[0]
    states: dict[int, BmsState] = {
        0: "idle", 1: "charging", 2: "discharging", 4: "disabled",
    }
    flags = struct.unpack_from("<I", data, 76)[0]
    protections = [label for mask, label in PROTECTION_FLAGS if flags & mask]
    known_mask = sum(mask for mask, _ in PROTECTION_FLAGS)
    unknown_flags = flags & ~known_mask
    if unknown_flags:
        protections.append(f"Unknown protection bits: 0x{unknown_flags:08X}")

    return BatteryTelemetry(
        timestamp=timestamp if timestamp is not None else time.time(),
        voltage_v=voltage_v,
        current_a=current_a,
        power_w=power_w,
        soc_percent=reported_soc if reported_soc is not None else soc_percent,
        remaining_ah=remaining_ah,
        capacity_ah=capacity_ah,
        cell_temp_c=cell_temp_c,
        bms_temp_c=bms_temp_c,
        cell_voltages_v=cell_voltages_v,
        reported_soc_percent=reported_soc,
        soc_source="bms" if reported_soc is not None else "capacity",
        soh_percent=float(soh_raw) if soh_raw <= 100 else None,
        cycle_count=struct.unpack_from("<I", data, 96)[0],
        bms_state_raw=state_raw,
        bms_state=states.get(state_raw, "unknown"),
        protection_flags=flags,
        active_protections=tuple(protections),
    )


class BatteryConnection:
    """One subscribed BLE client; callers must serialize requests."""

    def __init__(self, device: BLEDevice | str, timeout_sec: float = 10.0) -> None:
        from bleak import BleakClient
        self.client = BleakClient(device, timeout=timeout_sec)
        self.address = device.address if isinstance(device, BLEDevice) else device
        self.timeout = timeout_sec
        self.buffer = bytearray()
        self.ready = asyncio.Event()
        self.waiting = False

    def _notify(self, _sender: object, chunk: bytearray) -> None:
        if not self.waiting or self.ready.is_set():
            return
        self.buffer.extend(chunk[:MAX_RESPONSE_BYTES - len(self.buffer)])
        expected = expected_response_length(self.buffer)
        if len(self.buffer) >= MAX_RESPONSE_BYTES or (
            expected is not None and len(self.buffer) >= expected
        ):
            logger.debug("[DEBUG-resume] BLE response assembled address=%s bytes=%d expected=%s", self.address, len(self.buffer), expected)
            self.ready.set()

    async def connect(self) -> None:
        # Callers own cleanup, including partially connected/subscribed clients.
        logger.debug("[DEBUG-resume] BLE connect started address=%s timeout=%.3f", self.address, self.timeout)
        async with asyncio.timeout(self.timeout):
            await self.client.connect()
            logger.debug("[DEBUG-resume] BLE connect completed address=%s", self.address)
            logger.debug("[DEBUG-resume] BLE notification subscription started address=%s", self.address)
            await self.client.start_notify(TX_NOTIFY_UUID, self._notify)
            logger.debug("[DEBUG-resume] BLE notification subscription completed address=%s", self.address)

    async def close(self) -> None:
        # Disconnect also removes notification subscriptions.
        logger.debug("[DEBUG-resume] BLE disconnect started address=%s timeout=%.3f", self.address, self.timeout)
        async with asyncio.timeout(self.timeout):
            await self.client.disconnect()
        logger.debug("[DEBUG-resume] BLE disconnect completed address=%s", self.address)

    async def read(self) -> BatteryTelemetry:
        self.buffer.clear()
        self.ready.clear()
        self.waiting = True
        logger.debug("[DEBUG-resume] BLE status read started address=%s timeout=%.3f", self.address, self.timeout)
        try:
            async with asyncio.timeout(self.timeout):
                logger.debug("[DEBUG-resume] BLE status write started address=%s", self.address)
                await self.client.write_gatt_char(RX_WRITE_UUID, REQUEST_PAYLOAD, response=False)
                logger.debug("[DEBUG-resume] BLE status write completed address=%s awaiting_response=true", self.address)
                await self.ready.wait()
            logger.debug("[DEBUG-resume] BLE response validation started address=%s bytes=%d", self.address, len(self.buffer))
            return parse_bms_payload(bytes(self.buffer))
        finally:
            self.waiting = False
            logger.debug("[DEBUG-resume] BLE status read finished address=%s bytes=%d response_ready=%s", self.address, len(self.buffer), self.ready.is_set())


async def poll_battery(address: str, timeout_sec: float = 10.0) -> BatteryTelemetry:
    """Read once and disconnect, using the same lifecycle as retained clients."""
    connection = BatteryConnection(address, timeout_sec)
    try:
        await connection.connect()
        return await connection.read()
    finally:
        await connection.close()
