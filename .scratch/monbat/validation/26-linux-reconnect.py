"""Read-only Linux hardware check; run with the candidate src on PYTHONPATH.

The existing service must be stopped. Arguments: existing config, temporary DB.
This harness closes local BLE clients; it never resets adapters or writes controls.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import logging
from pathlib import Path
import sys
from time import monotonic

from bleak.backends.device import BLEDevice

from monbat import poller as module
from monbat.app import _load_config
from monbat.bms import BatteryConnection, BatteryTelemetry
from monbat.db import TelemetryRepository
from monbat.poller import Poller


events: list[tuple[str, str]] = []
clients: list[TrackedConnection] = []
scans = 0


def report(stage: str, **details: object) -> None:
    print(json.dumps({"stage": stage, **details}), flush=True)


class TrackedConnection(BatteryConnection):
    def __init__(self, device: BLEDevice, timeout_sec: float) -> None:
        assert isinstance(device, BLEDevice)
        self.device = device
        super().__init__(device, timeout_sec)
        clients.append(self)

    async def connect(self) -> None:
        events.append((self.device.address, "connect"))
        await super().connect()
        events.append((self.device.address, "subscribed"))

    async def read(self) -> BatteryTelemetry:
        events.append((self.device.address, "read"))
        result = await super().read()
        events.append((self.device.address, "valid_response"))
        return result

    async def close(self) -> None:
        events.append((self.device.address, "close"))
        await super().close()
        events.append((self.device.address, "closed"))


async def main() -> None:
    global scans
    config = _load_config(sys.argv[1])
    config = replace(config, poller=replace(config.poller, sqlite_path=sys.argv[2]))
    repo = TelemetryRepository(config.poller.sqlite_path)
    await repo.init_db()
    poller = Poller(config, repo)
    original_scan = module.BleakScanner.discover

    async def scan(*, timeout: float) -> list[BLEDevice]:
        global scans
        scans += 1
        assert scans == 1, "Rediscovery occurred during a cached reconnect check"
        return await original_scan(timeout=timeout)

    module.BleakScanner.discover = scan
    module.BatteryConnection = TrackedConnection
    poller.subscribe()
    try:
        report("initial_discovery", source=str(Path(module.__file__).resolve()))
        await poller._pass()
        available = tuple(b for b in config.batteries
                          if poller._batteries[b.id].connection is not None)
        assert available, "No configured Battery produced valid Telemetry"
        # Do not turn an unavailable Battery into an unrelated rediscovery test.
        poller._config = replace(config, batteries=available)
        report("initial_reads", available=[b.id for b in available], scans=scans)
        target = available[0]
        state = poller._batteries[target.id]
        old = state.connection
        assert isinstance(old, TrackedConnection)
        cached = state.device
        before = await repo.get_latest_telemetry(target.id)
        assert before is not None

        await old.close()  # Controlled local link loss, leaving Poller ownership intact.
        events.clear()
        await poller._pass()
        assert state.connection is None and state.failures == 1
        healthy = available[1:]
        for battery in healthy:
            assert events.index((battery.address, "valid_response")) < events.index((target.address, "close"))
        report("failed_read_cleanup", events=events, retry_seconds=state.retry_at - monotonic())

        await asyncio.sleep(max(0, state.retry_at - monotonic()) + 0.05)
        events.clear()
        await poller._pass()
        replacement = state.connection
        assert isinstance(replacement, TrackedConnection) and replacement is not old
        assert replacement.device is cached and scans == 1
        after = await repo.get_latest_telemetry(target.id)
        assert after is not None and after.timestamp > before.timestamp
        for battery in healthy:
            assert events.index((battery.address, "valid_response")) < events.index((target.address, "connect"))
        report("active_cached_reconnect", scans=scans, before=before.timestamp,
               after=after.timestamp, events=events)

        poller.unsubscribe()
        poller._grace_until = 0
        await poller._pass()  # Read retained clients, then disconnect for background.
        assert all(poller._batteries[b.id].connection is None for b in available)
        events.clear()
        before_background = after.timestamp
        await poller._pass()  # Every background connection must use the cache.
        latest = await repo.get_latest_telemetry(target.id)
        assert latest is not None and latest.timestamp > before_background
        assert scans == 1
        assert all(poller._batteries[b.id].connection is None for b in available)
        report("background_cached_reconnect", scans=scans, timestamp=latest.timestamp,
               events=events, clients=len(clients))
    finally:
        for battery_id in poller._batteries:
            await poller._close(battery_id)
        module.BleakScanner.discover = original_scan
        module.BatteryConnection = BatteryConnection
        report("cleanup", still_connected=[c.device.address for c in clients if c.client.is_connected])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
