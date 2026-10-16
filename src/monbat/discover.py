"""Discovery Script: interactive one-off CLI for `monbat discover`.

Scans BLE for batteries advertising service 0xFFE0, displays a numbered
table, prompts the user to select devices and assign friendly aliases, and
writes config.toml to the current working directory.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from bleak import BleakScanner
from bleak.backends.device import BLEDevice

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCAN_SECONDS: int = 10
_FILTER_PREFIXES: tuple[str, ...] = ("Redodo", "LiTime", "BMS")
_FFE0_UUID: str = "0000ffe0-0000-1000-8000-00805f9b34fb"
_CONFIG_PATH: str = "config.toml"

# ---------------------------------------------------------------------------
# Internal dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _SelectedBattery:
    id: str
    name: str
    mac_address: str


# ---------------------------------------------------------------------------
# BLE scan + filter
# ---------------------------------------------------------------------------


async def _scan() -> list[BLEDevice]:
    print(f"Scanning for BLE devices ({_SCAN_SECONDS} s)…")
    devices: list[BLEDevice] = await BleakScanner.discover(timeout=_SCAN_SECONDS)
    return devices


def _filter(devices: list[BLEDevice]) -> list[BLEDevice]:
    """Return devices that advertise 0xFFE0 or match known name prefixes.

    Falls back to the full list when nothing matches.
    """
    candidates = [
        d
        for d in devices
        if _FFE0_UUID in (d.metadata.get("uuids") or [])
        or (d.name or "").startswith(_FILTER_PREFIXES)
    ]
    if candidates:
        return candidates
    print("No filtered devices found — showing all discovered devices.")
    return devices


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------


def _print_table(devices: list[BLEDevice]) -> None:
    if not devices:
        print("No devices found.")
        return
    header = f"{'#':>3}  {'Name':<30}  {'MAC Address':<17}  {'RSSI':>6}"
    print()
    print(header)
    print("-" * len(header))
    for idx, device in enumerate(devices):
        name = (device.name or "<unknown>")[:30]
        rssi = device.rssi if device.rssi is not None else "n/a"
        rssi_str = f"{rssi} dBm" if isinstance(rssi, int) else str(rssi)
        print(f"{idx:>3}  {name:<30}  {device.address:<17}  {rssi_str:>6}")
    print()


# ---------------------------------------------------------------------------
# User prompts
# ---------------------------------------------------------------------------


def _prompt_selections(devices: list[BLEDevice]) -> list[BLEDevice]:
    """Ask the user to pick devices by index (comma-separated). Loops on bad input."""
    while True:
        raw = input("Enter device indices to add as batteries (e.g. 0,1): ").strip()
        if not raw:
            print("  Please enter at least one index.")
            continue
        parts = [p.strip() for p in raw.split(",")]
        indices: list[int] = []
        valid = True
        for part in parts:
            if not part.isdigit():
                print(f"  '{part}' is not a valid index.")
                valid = False
                break
            n = int(part)
            if n < 0 or n >= len(devices):
                print(f"  Index {n} is out of range (0–{len(devices) - 1}).")
                valid = False
                break
            indices.append(n)
        if not valid:
            continue
        return [devices[i] for i in indices]


def _prompt_alias(device: BLEDevice, position: int) -> tuple[str, str]:
    """Prompt for a human-readable name. Returns (slug_id, friendly_name)."""
    default_name = f"Battery {position}"
    raw = input(
        f"Friendly name for [{device.address}] (default: '{default_name}'): "
    ).strip()
    friendly = raw if raw else default_name
    slug = f"bat-{position}"
    return slug, friendly


# ---------------------------------------------------------------------------
# TOML serialisation (zero-dependency string builder)
# ---------------------------------------------------------------------------


def _serialize_config(batteries: list[_SelectedBattery]) -> str:
    lines: list[str] = [
        "[poller]",
        "poll_interval_seconds = 30",
        "timeout_seconds = 10.0",
        'sqlite_path = "monbat.db"',
        "",
        "[server]",
        'host = "0.0.0.0"',
        "port = 8000",
        "",
    ]
    for bat in batteries:
        lines += [
            "[[batteries]]",
            f'id = "{bat.id}"',
            f'name = "{bat.name}"',
            f'mac_address = "{bat.mac_address}"',
            "",
        ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Config file writer
# ---------------------------------------------------------------------------


def _write_config(toml_str: str, path: str = _CONFIG_PATH) -> None:
    target = Path(path)
    if target.exists():
        answer = input(
            f"'{path}' already exists. Overwrite? [y/N]: "
        ).strip().lower()
        if answer != "y":
            print("Aborted — existing config.toml was not changed.")
            return
    target.write_text(toml_str, encoding="utf-8")
    print(f"\nWritten to {target.resolve()}")


# ---------------------------------------------------------------------------
# Top-level coroutine
# ---------------------------------------------------------------------------


async def run_discover() -> None:
    all_devices = await _scan()

    if not all_devices:
        print("No BLE devices found. Make sure Bluetooth is enabled.")
        return

    devices = _filter(all_devices)
    _print_table(devices)

    selected = _prompt_selections(devices)

    batteries: list[_SelectedBattery] = []
    for position, device in enumerate(selected, start=1):
        slug, friendly = _prompt_alias(device, position)
        batteries.append(
            _SelectedBattery(id=slug, name=friendly, mac_address=device.address)
        )

    toml_str = _serialize_config(batteries)
    print("\nGenerated config.toml:\n")
    print(toml_str)

    _write_config(toml_str)
