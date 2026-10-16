"""BMS BLE driver for Redodo/LiTime LiFePO4 batteries.

Implements:
  - BatteryTelemetry dataclass
  - parse_bms_payload() — pure parser, no I/O, fully unit-testable
  - poll_battery()     — async BleakClient single-poll lifecycle
"""

from __future__ import annotations

import asyncio
import struct
import time
from dataclasses import dataclass

SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
TX_NOTIFY_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
RX_WRITE_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"
REQUEST_PAYLOAD: bytes = bytes([0x00, 0x00, 0x04, 0x01, 0x13, 0x55, 0xAA, 0x17])
MIN_PAYLOAD_LEN: int = 66


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


def parse_bms_payload(data: bytes, timestamp: float | None = None) -> BatteryTelemetry:
    """Parse a 66-byte little-endian BMS notification payload.

    Raises:
        ValueError: if the payload is shorter than MIN_PAYLOAD_LEN bytes.
    """
    if len(data) < MIN_PAYLOAD_LEN:
        raise ValueError(
            f"Payload too short: expected at least {MIN_PAYLOAD_LEN} bytes, got {len(data)}"
        )

    voltage_mv: int = struct.unpack_from("<I", data, 12)[0]
    voltage_v = round(voltage_mv / 1000.0, 3)

    raw_cells: tuple[int, ...] = struct.unpack_from("<16H", data, 16)
    cell_voltages_v = tuple(round(c / 1000.0, 3) for c in raw_cells if c > 0)

    current_ma: int = struct.unpack_from("<i", data, 48)[0]
    current_a = round(current_ma / 1000.0, 3)

    cell_temp_c: int = struct.unpack_from("<h", data, 52)[0]
    bms_temp_c: int = struct.unpack_from("<h", data, 54)[0]

    remaining_raw: int = struct.unpack_from("<H", data, 62)[0]
    remaining_ah = round(remaining_raw / 100.0, 2)

    capacity_raw: int = struct.unpack_from("<H", data, 64)[0]
    capacity_ah = round(capacity_raw / 100.0, 2)

    power_w = round(voltage_v * current_a, 2)
    soc_percent = (
        0.0
        if capacity_ah <= 0
        else min(100.0, max(0.0, round((remaining_ah / capacity_ah) * 100.0, 1)))
    )

    return BatteryTelemetry(
        timestamp=timestamp if timestamp is not None else time.time(),
        voltage_v=voltage_v,
        current_a=current_a,
        power_w=power_w,
        soc_percent=soc_percent,
        remaining_ah=remaining_ah,
        capacity_ah=capacity_ah,
        cell_temp_c=cell_temp_c,
        bms_temp_c=bms_temp_c,
        cell_voltages_v=cell_voltages_v,
    )


async def poll_battery(address: str, timeout_sec: float = 10.0) -> BatteryTelemetry:
    """Connect to a battery, request a telemetry frame, and disconnect.

    Performs a single connect → start_notify → write → await notification →
    stop_notify → disconnect cycle.

    Args:
        address:     Bluetooth MAC address of the battery BMS.
        timeout_sec: Seconds to wait for both connection and notification.

    Returns:
        Parsed BatteryTelemetry snapshot.

    Raises:
        ConnectionError: if the BleakClient fails to connect.
        TimeoutError:    if the notification does not arrive within timeout_sec.
    """
    from bleak import BleakClient  # local import keeps module importable without bleak

    raw_data = bytearray()
    notify_event = asyncio.Event()

    def _on_notification(_sender: int, chunk: bytearray) -> None:
        raw_data.extend(chunk)
        if len(raw_data) >= MIN_PAYLOAD_LEN:
            notify_event.set()

    async with BleakClient(address, timeout=timeout_sec) as client:
        if not client.is_connected:
            raise ConnectionError(f"Could not connect to battery at {address}")

        await client.start_notify(TX_NOTIFY_UUID, _on_notification)
        await client.write_gatt_char(RX_WRITE_UUID, REQUEST_PAYLOAD, response=False)

        try:
            async with asyncio.timeout(timeout_sec):
                await notify_event.wait()
        finally:
            await client.stop_notify(TX_NOTIFY_UUID)

    return parse_bms_payload(bytes(raw_data))
