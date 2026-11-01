"""Offline replay of a missing BlueZ object at the next background poll.

The real Poller and BatteryConnection run against external BLE fakes. Object
removal is an input captured in the service log; this does not model its cause.
The scan-first environment option is a causal probe, not a production patch.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
import os

import bleak
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
import pytest

from monbat import poller as module
from monbat.bms import BatteryConnection
from monbat.poller import Poller
from test_bms import REAL_STATUS
from test_recovery import Connection, Rig


def test_available_battery_needs_no_retry_after_background_object_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch, active=False)
        config = replace(rig.config, batteries=(rig.config.batteries[0],))
        rig.poller = Poller(config, rig.repo)
        available_paths: set[str] = set()
        attempts: list[str] = []

        async def discover(*, timeout: float) -> list[BLEDevice]:
            rig.scan_count += 1
            path = f"/synthetic/device/{rig.scan_count}"
            available_paths.add(path)
            battery = config.batteries[0]
            return [BLEDevice(battery.address, battery.name, {"path": path})]

        class Client:
            def __init__(self, device: BLEDevice, *, timeout: float) -> None:
                self.path = device.details["path"]
                self.callback: Callable[[object, bytearray], None] | None = None

            async def connect(self) -> None:
                attempts.append(self.path)
                if self.path not in available_paths:
                    raise BleakError(f"device '{self.path}' not found")

            async def start_notify(
                self, uuid: str, callback: Callable[[object, bytearray], None],
            ) -> None:
                self.callback = callback

            async def write_gatt_char(
                self, uuid: str, data: bytes, *, response: bool,
            ) -> None:
                assert self.callback is not None
                self.callback(0, bytearray(REAL_STATUS))

            async def disconnect(self) -> None:
                pass

        monkeypatch.setattr(module.BleakScanner, "discover", discover)
        monkeypatch.setattr(bleak, "BleakClient", Client)
        monkeypatch.setattr(module, "BatteryConnection", BatteryConnection)

        async def scheduled_pass() -> None:
            if os.environ.get("MONBAT_DIAGNOSTIC_PROBE") == "scan-first":
                for state in rig.poller._batteries.values():
                    if state.connection is None:
                        state.rediscover = True
            await rig.poller._pass()

        await scheduled_pass()
        assert len(rig.repo.saved) == 1
        # The next long-gap poll has no live Device1 object, as in the log.
        if os.environ.get("MONBAT_DIAGNOSTIC_PROBE") != "object-preserved":
            available_paths.clear()
        rig.clock += 1800
        await scheduled_pass()
        saved_at_due = len(rig.repo.saved) - 1
        state = rig.poller._batteries[config.batteries[0].id]
        retry_delay = max(0.0, state.retry_at - rig.clock)
        if state.failures and os.environ.get("MONBAT_DIAGNOSTIC_MINIMAL") != "1":
            rig.clock = state.retry_at
            await rig.poller._pass(retry_only=True)
        print(
            f"saved_at_due={saved_at_due} scans={rig.scan_count} "
            f"connection_attempts={len(attempts)} retry_delay={retry_delay:.0f}s "
            f"saved_after_retry={len(rig.repo.saved) - 1}"
        )
        assert saved_at_due == 1, (
            "Available Battery incurs a failed cached attempt and backoff before "
            "the discovery that a discover-first poll would perform immediately"
        )

    asyncio.run(scenario())


def test_near_simultaneous_cache_misses_share_one_recovery_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch, active=False)
        present: set[int] = set()
        base_factory = rig.connection

        async def discover(*, timeout: float) -> list[BLEDevice]:
            rig.scan_count += 1
            rig.clock += 10
            devices = [BLEDevice(b.address, b.name, {}) for b in rig.config.batteries]
            present.update(id(device) for device in devices)
            return devices

        def connection(device: BLEDevice, timeout: float) -> Connection:
            client = base_factory(device, timeout)
            original_connect = client.connect

            async def connect() -> None:
                if id(device) not in present:
                    # Sequential failures are almost simultaneous, but their
                    # per-Battery monotonic retry deadlines are not identical.
                    rig.clock += 0.001
                    raise BleakError("device '/synthetic/stale' not found")
                rig.clock += 4
                await original_connect()

            client.connect = connect
            return client

        monkeypatch.setattr(module.BleakScanner, "discover", discover)
        monkeypatch.setattr(module, "BatteryConnection", connection)
        await rig.poller._pass()
        present.clear()
        rig.clock = 1900
        scans_before_retry = rig.scan_count
        await rig.poller._pass()
        retry_offsets = [
            s.retry_at - 1900 for s in rig.poller._batteries.values() if s.failures
        ]
        if os.environ.get("MONBAT_DIAGNOSTIC_PROBE") == "batch-deadlines":
            deadline = max(s.retry_at for s in rig.poller._batteries.values())
            for state in rig.poller._batteries.values():
                state.retry_at = deadline
        while any(s.failures for s in rig.poller._batteries.values()):
            deadline = rig.poller._next_retry_at()
            assert deadline is not None
            rig.clock = max(rig.clock, deadline)
            await rig.poller._pass(retry_only=True)
        recovery_scans = rig.scan_count - scans_before_retry
        print(
            f"retry_offsets={retry_offsets} recovery_scans={recovery_scans} "
            f"both_saved_after={rig.clock - 1900:.3f}s"
        )
        assert recovery_scans == 1, (
            "Millisecond deadline drift splits shared rediscovery into two scans"
        )

    asyncio.run(scenario())
