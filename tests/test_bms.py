"""Tests for monbat.bms — offline unit tests + live-hardware integration smoke tests.

Run offline only:
    uv run pytest tests/test_bms.py -k "not integration"

Run with live hardware (requires Bluetooth + batteries from config.toml):
    uv run pytest tests/test_bms.py -m integration
"""

from __future__ import annotations

import asyncio
import struct
import tomllib
from pathlib import Path
from collections.abc import Callable
from types import TracebackType

import pytest
from bleak import BleakScanner
from bleak.exc import BleakError

from monbat.bms import BatteryTelemetry, MIN_PAYLOAD_LEN, PROTECTION_FLAGS, expected_response_length, parse_bms_payload, poll_battery

# ---------------------------------------------------------------------------
# Helpers (only used by tests — not exported by production bms.py)
# ---------------------------------------------------------------------------

def _build_payload(
    voltage_v: float = 13.300,
    cells_v: tuple[float, ...] = (3.325, 3.325, 3.325, 3.325),
    current_a: float = 15.500,
    cell_temp_c: int = 24,
    bms_temp_c: int = 27,
    remaining_ah: float = 85.0,
    capacity_ah: float = 100.0,
    reported_soc: int = 65535,
    state: int = 0,
    protections: int = 0,
    soh: int = 100,
    cycles: int = 123,
) -> bytes:
    """Build a valid MIN_PAYLOAD_LEN-byte BMS frame for testing."""
    buf = bytearray(105)
    buf[:8] = bytes.fromhex("000065019355aa00")
    struct.pack_into("<H", buf, 12, int(voltage_v * 1000))
    for idx, c_v in enumerate(cells_v):
        struct.pack_into("<H", buf, 16 + idx * 2, int(c_v * 1000))
    struct.pack_into("<i", buf, 48, int(current_a * 1000))
    struct.pack_into("<h", buf, 52, cell_temp_c)
    struct.pack_into("<h", buf, 54, bms_temp_c)
    struct.pack_into("<H", buf, 62, int(remaining_ah * 100))
    struct.pack_into("<I", buf, 64, int(capacity_ah * 100))
    struct.pack_into("<I", buf, 76, protections)
    struct.pack_into("<H", buf, 88, state)
    struct.pack_into("<H", buf, 90, reported_soc)
    struct.pack_into("<I", buf, 92, soh)
    struct.pack_into("<I", buf, 96, cycles)
    buf[-1] = sum(buf[:-1]) & 255
    return bytes(buf)


def _load_battery_addresses() -> list[str]:
    """Read Bleak device addresses from config.toml in the repo root."""
    config_path = Path(__file__).parent.parent / "config.toml"
    if not config_path.exists():
        return []
    with config_path.open("rb") as fh:
        cfg = tomllib.load(fh)
    return [
        battery.get("address", battery.get("mac_address", ""))
        for battery in cfg.get("batteries", [])
    ]


# ---------------------------------------------------------------------------
# Offline unit tests
# ---------------------------------------------------------------------------

class TestParseBmsPayload:
    def test_round_trip(self) -> None:
        """All fields must parse back to the values packed by _build_payload."""
        cells = (3.310, 3.320, 3.325, 3.330)
        payload = _build_payload(
            voltage_v=13.285,
            cells_v=cells,
            current_a=10.100,
            cell_temp_c=23,
            bms_temp_c=26,
            remaining_ah=92.50,
            capacity_ah=100.0,
        )
        t = parse_bms_payload(payload, timestamp=1_000_000.0)

        assert isinstance(t, BatteryTelemetry)
        assert t.timestamp == 1_000_000.0
        assert t.voltage_v == pytest.approx(13.285, abs=0.001)
        assert t.current_a == pytest.approx(10.100, abs=0.001)
        assert t.power_w == pytest.approx(13.285 * 10.100, abs=0.02)
        assert t.soc_percent == pytest.approx(92.5, abs=0.1)
        assert t.remaining_ah == pytest.approx(92.50, abs=0.01)
        assert t.capacity_ah == pytest.approx(100.0, abs=0.01)
        assert t.cell_temp_c == 23
        assert t.bms_temp_c == 26
        assert len(t.cell_voltages_v) == 4
        for parsed, expected in zip(t.cell_voltages_v, cells):
            assert parsed == pytest.approx(expected, abs=0.001)

    def test_too_short_raises(self) -> None:
        with pytest.raises(ValueError, match="Payload too short"):
            parse_bms_payload(bytes(MIN_PAYLOAD_LEN - 1))

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="Payload too short"):
            parse_bms_payload(b"")

    def test_discharge_negative_current(self) -> None:
        """Negative current must yield negative power (discharging state)."""
        payload = _build_payload(current_a=-8.250, voltage_v=12.950)
        t = parse_bms_payload(payload)
        assert t.current_a < 0
        assert t.power_w < 0

    def test_soc_zero_capacity(self) -> None:
        """SOC must be 0.0 when capacity_ah is 0 (no divide-by-zero)."""
        payload = _build_payload(remaining_ah=0.0, capacity_ah=0.0)
        t = parse_bms_payload(payload)
        assert t.soc_percent == 0.0

    def test_soc_clamps_at_100(self) -> None:
        """SOC is clamped to 100.0 even if remaining > capacity."""
        payload = _build_payload(remaining_ah=110.0, capacity_ah=100.0)
        t = parse_bms_payload(payload)
        assert t.soc_percent == 100.0

    def test_zero_cell_voltages_filtered(self) -> None:
        """Cells with 0 mV (unused slots) are excluded from cell_voltages_v."""
        # Only 4 cells packed; the remaining 12 slots stay zero
        payload = _build_payload(cells_v=(3.300, 3.300, 3.300, 3.300))
        t = parse_bms_payload(payload)
        assert len(t.cell_voltages_v) == 4

    def test_telemetry_is_immutable(self) -> None:
        """BatteryTelemetry must be frozen (attempt to assign should raise)."""
        t = parse_bms_payload(_build_payload())
        with pytest.raises((AttributeError, TypeError)):
            t.voltage_v = 0.0  # type: ignore[misc]

    def test_timestamp_defaults_to_now(self) -> None:
        import time
        before = time.time()
        t = parse_bms_payload(_build_payload())
        after = time.time()
        assert before <= t.timestamp <= after


# ---------------------------------------------------------------------------
# Live-hardware integration smoke tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestLiveBatteries:
    """Requires physical Bluetooth adapter + batteries listed in config.toml."""

    def _skip_if_no_bluetooth(self) -> None:
        """Skip the test if Bleak cannot access a Bluetooth adapter."""
        try:
            asyncio.run(BleakScanner.discover(timeout=1.0))
        except (BleakError, OSError) as exc:
            pytest.skip(f"Bluetooth adapter unavailable: {exc}")

    @pytest.fixture(autouse=True)
    def check_bt(self) -> None:
        self._skip_if_no_bluetooth()

    def _poll(self, address: str) -> BatteryTelemetry:
        return asyncio.run(poll_battery(address, timeout_sec=15.0))

    @pytest.mark.parametrize("address", _load_battery_addresses())
    def test_live_poll(self, address: str) -> None:
        """Poll each battery from config.toml and assert telemetry is sane."""
        if not address:
            pytest.skip("No batteries configured in config.toml")

        t = self._poll(address)

        # Sanity bounds for a healthy LiFePO4 pack
        # 8S LiFePO4 pack: ~21–29 V; allow 8–32 V to cover any S configuration
        assert 8.0 <= t.voltage_v <= 32.0, f"Voltage out of range: {t.voltage_v} V"
        assert 0.0 <= t.soc_percent <= 100.0, f"SOC out of range: {t.soc_percent} %"
        assert t.capacity_ah > 0, "capacity_ah must be positive"
        assert 0.0 <= t.remaining_ah <= t.capacity_ah + 1.0  # +1 tolerance
        assert len(t.cell_voltages_v) >= 1, "No cell voltages parsed"
        assert all(2.5 <= v <= 4.0 for v in t.cell_voltages_v), (
            f"Cell voltage out of LiFePO4 range: {t.cell_voltages_v}"
        )
        assert -60 <= t.cell_temp_c <= 60, f"Cell temp out of range: {t.cell_temp_c} °C"
        assert -60 <= t.bms_temp_c <= 60, f"BMS temp out of range: {t.bms_temp_c} °C"

        print(f"\n[{address}] {t.voltage_v} V | {t.current_a} A | {t.soc_percent} % SOC")
        print(f"  cells={t.cell_voltages_v}  T_cell={t.cell_temp_c}°C  T_bms={t.bms_temp_c}°C")


# Captured R-12100 response, mkeguy106/bmsmon BmsProtocolTest.kt,
# commit 4534382d00702e14199e2a2aaab50180cf0878ac.
REAL_STATUS = bytes.fromhex(
    "000065019355aa007c3300000c340000030d030d030d030d00000000000000000000000000000000000000000000000000000000170018000000000000001027102700000000000000000000000000000000000000000000000063006400000000000000000000008b"
)


def test_captured_status_and_prefix() -> None:
    for prefix in (b"", bytes.fromhex("aabbccddee")):
        t = parse_bms_payload(prefix + REAL_STATUS)
        assert t.voltage_v == 13.324
        assert t.soc_percent == 99
        assert t.remaining_ah == t.capacity_ah == 100
        assert t.soc_source == "bms"
        assert t.soh_percent == 100
        assert t.cycle_count == 0
        assert t.bms_state == "idle"
        assert t.active_protections == ()
        assert expected_response_length(prefix + REAL_STATUS) == len(prefix) + 105


@pytest.mark.parametrize("length", [66, 80, 100, 104])
def test_truncated_capture_is_rejected(length: int) -> None:
    assert expected_response_length(REAL_STATUS[:length]) == 105
    with pytest.raises(ValueError):
        parse_bms_payload(REAL_STATUS[:length])


@pytest.mark.parametrize("offset,value", [(4, 0x90), (2, 60), (2, 120), (12, 0)])
def test_corrupt_header_length_or_checksum(offset: int, value: int) -> None:
    frame = bytearray(REAL_STATUS)
    frame[offset] = value
    with pytest.raises(ValueError):
        parse_bms_payload(bytes(frame))


def test_8s_voltage_and_wide_capacity() -> None:
    t = parse_bms_payload(_build_payload(
        voltage_v=26.6, cells_v=(3.325,) * 8, capacity_ah=1000,
        current_a=-10, reported_soc=0,
    ))
    assert t.voltage_v == 26.6
    assert t.capacity_ah == 1000
    assert len(t.cell_voltages_v) == 8
    assert t.power_w == -266
    assert t.soc_percent == 0
    assert t.soc_source == "bms"


@pytest.mark.parametrize("mask,label", PROTECTION_FLAGS)
def test_each_protection(mask: int, label: str) -> None:
    t = parse_bms_payload(_build_payload(protections=mask))
    assert t.protection_flags == mask
    assert t.active_protections == (label,)


def test_unknown_bits_state_and_unavailable_soc_soh() -> None:
    t = parse_bms_payload(_build_payload(
        protections=0x80000004, state=42, reported_soc=65535, soh=0xffffffff,
    ))
    assert t.bms_state == "unknown"
    assert t.bms_state_raw == 42
    assert t.active_protections == ("Overcharge", "Unknown protection bits: 0x80000000")
    assert t.reported_soc_percent is None
    assert t.soh_percent is None
    assert t.soc_source == "capacity"
    assert t.soc_percent == 85


@pytest.mark.parametrize("raw,state", [(0, "idle"), (1, "charging"), (2, "discharging"), (4, "disabled")])
def test_bms_state(raw: int, state: str) -> None:
    assert parse_bms_payload(_build_payload(state=raw)).bms_state == state


@pytest.mark.parametrize("scenario", ["complete", "truncated", "corrupt", "overflow", "write-failure"])
def test_poll_reassembles_and_disconnects(monkeypatch: pytest.MonkeyPatch, scenario: str) -> None:
    import bleak
    calls: list[str] = []

    class Client:
        is_connected = True
        callback: Callable[[int, bytearray], None]

        def __init__(self, address: str, timeout: float) -> None:
            assert address == "test"

        async def __aenter__(self) -> Client:
            calls.append("connect")
            return self

        async def __aexit__(self, exc_type: type[BaseException] | None,
                            exc: BaseException | None, traceback: TracebackType | None) -> None:
            calls.append("disconnect")

        async def start_notify(self, uuid: str, callback: Callable[[int, bytearray], None]) -> None:
            self.callback = callback
            calls.append("notify")

        async def write_gatt_char(self, uuid: str, request: bytes, response: bool) -> None:
            assert request == bytes.fromhex("000004011355aa17")
            if scenario == "write-failure":
                raise OSError("write failed")
            frame = bytearray(REAL_STATUS)
            if scenario == "corrupt":
                frame[-1] ^= 1
            if scenario == "truncated":
                frame = frame[:80]
            if scenario == "overflow":
                frame = bytearray(b"x" * 1000)
            for i in range(0, len(frame), 20):
                self.callback(0, bytearray(frame[i:i + 20]))
                await asyncio.sleep(0)
            calls.append("write")

        async def stop_notify(self, uuid: str) -> None:
            calls.append("stop")

    monkeypatch.setattr(bleak, "BleakClient", Client)
    if scenario == "complete":
        assert asyncio.run(poll_battery("test")).soc_percent == 99
    else:
        error = TimeoutError if scenario == "truncated" else OSError if scenario == "write-failure" else ValueError
        with pytest.raises(error):
            asyncio.run(poll_battery("test", timeout_sec=0.01))
    assert calls[:2] == ["connect", "notify"]
    assert calls[-2:] == ["stop", "disconnect"]
