"""PROTOTYPE: BMS BLE Protocol & Driver.

Throwaway prototype validating byte layout, payload parsing, and bleak client structure
for Redodo/LiTime LiFePO4 batteries.
"""

from __future__ import annotations

import asyncio
import struct
import sys

from monbat.bms import parse_bms_payload, poll_battery as poll_battery_bleak


def build_synthetic_payload(
    voltage_v: float = 13.300,
    cells_v: tuple[float, ...] = (3.325, 3.325, 3.325, 3.325),
    current_a: float = 15.500,
    cell_temp_c: int = 24,
    bms_temp_c: int = 27,
    remaining_ah: float = 85.0,
    capacity_ah: float = 100.0,
) -> bytes:
    """Constructs a valid framed BMS frame for testing."""
    buf = bytearray(105)
    buf[:8] = bytes.fromhex("000065019355aa00")

    struct.pack_into("<H", buf, 12, int(voltage_v * 1000))

    for idx, c_v in enumerate(cells_v):
        struct.pack_into("<H", buf, 16 + (idx * 2), int(c_v * 1000))

    struct.pack_into("<i", buf, 48, int(current_a * 1000))
    struct.pack_into("<h", buf, 52, cell_temp_c)
    struct.pack_into("<h", buf, 54, bms_temp_c)
    struct.pack_into("<H", buf, 62, int(remaining_ah * 100))
    struct.pack_into("<I", buf, 64, int(capacity_ah * 100))

    struct.pack_into("<H", buf, 90, 85)
    struct.pack_into("<I", buf, 92, 100)
    buf[-1] = sum(buf[:-1]) & 255
    return bytes(buf)


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
