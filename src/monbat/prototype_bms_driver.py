"""PROTOTYPE: BMS BLE Protocol & Driver.

Throwaway prototype validating byte layout, payload parsing, and bleak client structure
for Redodo/LiTime LiFePO4 batteries.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import struct
import sys
import time

SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
TX_NOTIFY_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
RX_WRITE_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"
REQUEST_PAYLOAD = bytes([0x00, 0x00, 0x04, 0x01, 0x13, 0x55, 0xAA, 0x17])
MIN_PAYLOAD_LEN = 66


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
    if len(data) < MIN_PAYLOAD_LEN:
        raise ValueError(f"Payload too short: expected at least {MIN_PAYLOAD_LEN} bytes, got {len(data)}")

    # Unpack little-endian fields
    voltage_mv = struct.unpack_from("<I", data, 12)[0]
    voltage_v = round(voltage_mv / 1000.0, 3)

    raw_cells = struct.unpack_from("<16H", data, 16)
    cell_voltages = tuple(round(c / 1000.0, 3) for c in raw_cells if c > 0)

    current_ma = struct.unpack_from("<i", data, 48)[0]
    current_a = round(current_ma / 1000.0, 3)

    cell_temp_c = struct.unpack_from("<h", data, 52)[0]
    bms_temp_c = struct.unpack_from("<h", data, 54)[0]

    remaining_raw = struct.unpack_from("<H", data, 62)[0]
    remaining_ah = round(remaining_raw / 100.0, 2)

    capacity_raw = struct.unpack_from("<H", data, 64)[0]
    capacity_ah = round(capacity_raw / 100.0, 2)

    power_w = round(voltage_v * current_a, 2)
    soc_percent = 0.0 if capacity_ah <= 0 else min(100.0, max(0.0, round((remaining_ah / capacity_ah) * 100.0, 1)))

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
        cell_voltages_v=cell_voltages,
    )


def build_synthetic_payload(
    voltage_v: float = 13.300,
    cells_v: tuple[float, ...] = (3.325, 3.325, 3.325, 3.325),
    current_a: float = 15.500,
    cell_temp_c: int = 24,
    bms_temp_c: int = 27,
    remaining_ah: float = 85.0,
    capacity_ah: float = 100.0,
) -> bytes:
    """Constructs a valid 66-byte BMS frame for testing."""
    buf = bytearray(MIN_PAYLOAD_LEN)

    struct.pack_into("<I", buf, 12, int(voltage_v * 1000))

    for idx, c_v in enumerate(cells_v):
        struct.pack_into("<H", buf, 16 + (idx * 2), int(c_v * 1000))

    struct.pack_into("<i", buf, 48, int(current_a * 1000))
    struct.pack_into("<h", buf, 52, cell_temp_c)
    struct.pack_into("<h", buf, 54, bms_temp_c)
    struct.pack_into("<H", buf, 62, int(remaining_ah * 100))
    struct.pack_into("<H", buf, 64, int(capacity_ah * 100))

    return bytes(buf)


async def poll_battery_bleak(address: str, timeout_sec: float = 10.0) -> BatteryTelemetry:
    """Async connect-read-disconnect driver using bleak."""
    # Imported inside function so prototype runs in simulation mode without bleak installed
    from bleak import BleakClient

    raw_data = bytearray()
    notify_event = asyncio.Event()

    def on_notification(_sender: int, chunk: bytearray) -> None:
        raw_data.extend(chunk)
        if len(raw_data) >= MIN_PAYLOAD_LEN:
            notify_event.set()

    async with BleakClient(address, timeout=timeout_sec) as client:
        if not client.is_connected:
            raise ConnectionError(f"Could not connect to battery at {address}")

        await client.start_notify(TX_NOTIFY_UUID, on_notification)
        await client.write_gatt_char(RX_WRITE_UUID, REQUEST_PAYLOAD, response=False)

        try:
            async with asyncio.timeout(timeout_sec):
                await notify_event.wait()
        finally:
            await client.stop_notify(TX_NOTIFY_UUID)

    return parse_bms_payload(bytes(raw_data))


def main() -> None:
    print("=== BMS Driver Prototype Simulation ===")
    sample_buf = build_synthetic_payload()
    print(f"Constructed synthetic payload ({len(sample_buf)} bytes)")

    telemetry = parse_bms_payload(sample_buf)
    print("Successfully parsed telemetry:")
    print(f"  Voltage:      {telemetry.voltage_v} V")
    print(f"  Current:      {telemetry.current_a} A")
    print(f"  Power:        {telemetry.power_w} W")
    print(f"  SOC:          {telemetry.soc_percent} %")
    print(f"  Capacity:     {telemetry.remaining_ah} / {telemetry.capacity_ah} Ah")
    print(f"  Cell Temp:    {telemetry.cell_temp_c} °C")
    print(f"  BMS Temp:     {telemetry.bms_temp_c} °C")
    print(f"  Cells ({len(telemetry.cell_voltages_v)}S):   {telemetry.cell_voltages_v}")

    # Test edge case: discharge state
    discharge_buf = build_synthetic_payload(current_a=-8.250, voltage_v=12.950)
    disch_telemetry = parse_bms_payload(discharge_buf)
    print("\nDischarge test:")
    print(f"  Current:      {disch_telemetry.current_a} A")
    print(f"  Power:        {disch_telemetry.power_w} W (negative = discharging)")

    # Live BLE invocation if address supplied
    if len(sys.argv) > 1:
        address = sys.argv[1]
        print(f"\nAttempting live connection to {address}...")
        res = asyncio.run(poll_battery_bleak(address))
        print(f"Live result: {res}")


if __name__ == "__main__":
    main()
