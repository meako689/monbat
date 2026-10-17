"""Discovery Script: interactive one-off CLI for `monbat discover`.

Scans BLE for batteries advertising service 0xFFE0, displays a numbered
table, prompts the user to select devices and assign friendly aliases, and
writes config.toml to the current working directory.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, asdict
from time import monotonic

from monbat.app import AppConfig, _load_config
from monbat.bms import BatteryConnection
from pathlib import Path

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCAN_SECONDS: int = 10
_FILTER_PREFIXES: tuple[str, ...] = ("Redodo", "LiTime", "BMS")
_FFE0_UUID: str = "0000ffe0-0000-1000-8000-00805f9b34fb"
_CONFIG_PATH: str = "config.toml"

# Convenience alias for a (device, advertisement) pair
_DeviceAdv = tuple[BLEDevice, AdvertisementData]

# ---------------------------------------------------------------------------
# Internal dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _SelectedBattery:
    id: str
    name: str
    address: str


# ---------------------------------------------------------------------------
# BLE scan + filter
# ---------------------------------------------------------------------------


async def _scan() -> list[_DeviceAdv]:
    """Scan for _SCAN_SECONDS and return (device, adv) pairs."""
    print(f"Scanning for BLE devices ({_SCAN_SECONDS} s)…")
    result: dict[str, tuple[BLEDevice, AdvertisementData]] = (
        await BleakScanner.discover(timeout=_SCAN_SECONDS, return_adv=True)
    )
    return list(result.values())


def _filter(pairs: list[_DeviceAdv]) -> list[_DeviceAdv]:
    """Return pairs advertising 0xFFE0 or matching known name prefixes.

    Falls back to the full list when nothing matches.
    """
    candidates = [
        (device, adv)
        for device, adv in pairs
        if _FFE0_UUID in adv.service_uuids
        or (device.name or adv.local_name or "").startswith(_FILTER_PREFIXES)
    ]
    if candidates:
        return candidates
    print("No filtered devices found — showing all discovered devices.")
    return pairs


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------


def _print_table(pairs: list[_DeviceAdv]) -> None:
    if not pairs:
        print("No devices found.")
        return
    header = f"{'#':>3}  {'Name':<30}  {'Address':<36}  {'RSSI':>10}"
    print()
    print(header)
    print("-" * len(header))
    for idx, (device, adv) in enumerate(pairs):
        name = (device.name or adv.local_name or "<unknown>")[:30]
        rssi_str = f"{adv.rssi} dBm"
        print(f"{idx:>3}  {name:<30}  {device.address:<36}  {rssi_str:>10}")
    print()


# ---------------------------------------------------------------------------
# User prompts
# ---------------------------------------------------------------------------


def _prompt_selections(pairs: list[_DeviceAdv], defaults: list[int] | None = None) -> list[_DeviceAdv]:
    """Ask the user to pick devices by index (comma-separated). Loops on bad input."""
    while True:
        raw = input("Enter device indices to add as batteries (e.g. 0,1): ").strip()
        if not raw and defaults:
            return [pairs[i] for i in defaults]
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
            if n < 0 or n >= len(pairs):
                print(f"  Index {n} is out of range (0–{len(pairs) - 1}).")
                valid = False
                break
            if n not in indices:
                indices.append(n)
        if not valid:
            continue
        return [pairs[i] for i in indices]


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


def _serialize_config(
    batteries: list[_SelectedBattery], existing: AppConfig | None = None,
    concurrency: int = 1,
) -> str:
    poller = asdict(existing.poller) if existing else {
        "poll_interval_seconds": 600, "active_interval_seconds": 10,
        "timeout_seconds": 10.0, "freshness_seconds": 60,
        "sqlite_path": "monbat.db", "persistent_connections": True,
    }
    poller["concurrency"] = concurrency
    server = asdict(existing.server) if existing else {"host": "0.0.0.0", "port": 8000}
    def literal(value: str | float | int | bool) -> str:
        return json.dumps(value, ensure_ascii=False)
    lines = ["[poller]"]
    lines.extend(f"{key} = {literal(value)}" for key, value in poller.items())
    lines.extend(["", "[server]"])
    lines.extend(f"{key} = {literal(value)}" for key, value in server.items())
    for battery in batteries:
        lines.extend(["", "[[batteries]]"])
        lines.extend(f"{key} = {literal(value)}" for key, value in asdict(battery).items())
    return "\n".join(lines) + "\n"


async def _test_concurrency(selected: list[_DeviceAdv], timeout: float) -> int:
    """Test retained clients with sequential and concurrent status requests."""
    clients: list[BatteryConnection] = []
    limit = min(2, len(selected))
    sequential_ok = False
    try:
        for device, _adv in selected:
            client = BatteryConnection(device, timeout)
            clients.append(client)
            await client.connect()
        for concurrency in sorted({1, limit}):
            semaphore = asyncio.Semaphore(concurrency)
            async def read(client: BatteryConnection) -> None:
                async with semaphore:
                    await client.read()
            durations: list[float] = []
            for round_number in range(3):
                started = monotonic()
                results = await asyncio.gather(*(read(c) for c in clients), return_exceptions=True)
                if any(isinstance(result, BaseException) for result in results):
                    raise RuntimeError(f"Read failed with concurrency {concurrency}: {results}")
                durations.append(monotonic() - started)
                if round_number < 2:
                    await asyncio.sleep(max(0, 10 - durations[-1]))
            print(f"Concurrency {concurrency}: 3 valid rounds; average {sum(durations)/3:.3f}s")
            sequential_ok = True
        print(f"Saving tested concurrency: {limit}")
        return limit
    except Exception as exc:
        print(f"Hardware test failed: {exc}. Saving conservative concurrency 1.")
        if not sequential_ok:
            print("Persistent multi-Battery operation could not be validated.")
        return 1
    finally:
        for client in clients:
            try:
                await client.close()
            except Exception as exc:
                print(f"Disconnect failed: {exc}")


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
    existing = _load_config(_CONFIG_PATH) if Path(_CONFIG_PATH).exists() else None
    pairs = await _scan()

    if not pairs:
        print("No BLE devices found. Make sure Bluetooth is enabled.")
        return

    filtered = _filter(pairs)
    _print_table(filtered)

    saved = {b.address: b for b in existing.batteries} if existing else {}
    defaults = [i for i, (device, _) in enumerate(filtered) if device.address in saved]
    if defaults:
        print(f"Press Enter to reuse discovered configured Batteries: {','.join(map(str, defaults))}")
    selected = _prompt_selections(filtered, defaults)

    batteries: list[_SelectedBattery] = []
    for position, (device, _adv) in enumerate(selected, start=1):
        if device.address in saved:
            previous = saved[device.address]
            slug, friendly = previous.id, previous.name
            print(f"Reusing {friendly} ({slug})")
        else:
            slug, friendly = _prompt_alias(device, position)
            used = {b.id for b in batteries} | {b.id for b in saved.values()}
            suffix = position
            while slug in used:
                suffix += 1
                slug = f"bat-{suffix}"
        batteries.append(
            _SelectedBattery(id=slug, name=friendly, address=device.address)
        )

    concurrency = await _test_concurrency(selected, existing.poller.timeout_seconds if existing else 10)
    toml_str = _serialize_config(batteries, existing, concurrency)
    print("\nGenerated config.toml:\n")
    print(toml_str)

    _write_config(toml_str)
