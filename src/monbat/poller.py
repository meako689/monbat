"""Browser-aware collection with independently retained Battery connections."""
from __future__ import annotations

import asyncio
import logging
from time import monotonic
from typing import TYPE_CHECKING, Literal

from bleak import BleakScanner
from monbat.bms import BatteryConnection
from monbat.db import TelemetryRepository

if TYPE_CHECKING:
    from monbat.app import AppConfig, BatteryConfig

logger = logging.getLogger(__name__)


class Poller:
    def __init__(self, config: AppConfig, repo: TelemetryRepository) -> None:
        self._config = config
        self._repo = repo
        self._wake = asyncio.Event()
        self._stopped = False
        self._running = True
        self._last_started: float | None = None
        self._subscribers = 0
        self._grace_until = 0.0
        self._connections: dict[str, BatteryConnection] = {}
        self._persistent_ids: set[str] = set()
        self._retry_at: dict[str, float] = {}
        self._failures: dict[str, int] = {}

    def subscribe(self) -> None:
        self._subscribers += 1
        if self._subscribers == 1:
            self._wake.set()

    def unsubscribe(self) -> None:
        self._subscribers = max(0, self._subscribers - 1)
        if self._subscribers == 0:
            self._grace_until = monotonic() + 30
            self._wake.set()

    def _active(self) -> bool:
        return self._subscribers > 0 or monotonic() < self._grace_until

    def request_refresh(self) -> Literal["accepted", "skipped", "disabled"]:
        if self._stopped:
            return "disabled"
        if self._running or self._wake.is_set():
            return "skipped"
        if self._last_started is not None and monotonic() - self._last_started < 30:
            return "skipped"
        self._wake.set()
        return "accepted"

    async def _close(self, battery_id: str) -> None:
        connection = self._connections.pop(battery_id, None)
        if connection is not None:
            persistent = battery_id in self._persistent_ids
            self._persistent_ids.discard(battery_id)
            try:
                await connection.close()
                if persistent:
                    logger.info("Persistent BLE connection finished for battery %s", battery_id)
            except Exception:
                logger.warning("Disconnect failed for %s", battery_id, exc_info=True)

    async def _read(self, battery: BatteryConfig, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            try:
                telemetry = await self._connections[battery.id].read()
                await self._repo.save_telemetry(battery.id, telemetry)
                self._failures.pop(battery.id, None)
                self._retry_at.pop(battery.id, None)
            except Exception:
                self._failed(battery.id)
                await self._close(battery.id)
            finally:
                if not self._active() or not self._config.poller.persistent_connections:
                    await self._close(battery.id)

    def _failed(self, battery_id: str) -> None:
        count = min(self._failures.get(battery_id, 0) + 1, 4)
        self._failures[battery_id] = count
        self._retry_at[battery_id] = monotonic() + min(10 * 2 ** (count - 1), 60)
        logger.warning("Poll failed for battery %s", battery_id, exc_info=True)

    async def _pass(self) -> None:
        batteries = [b for b in self._config.batteries if monotonic() >= self._retry_at.get(b.id, 0)]
        missing = [b for b in batteries if b.id not in self._connections]
        if missing:
            try:
                devices = await BleakScanner.discover(timeout=self._config.poller.timeout_seconds)
                found = {d.address: d for d in devices}
            except Exception:
                for battery in missing:
                    self._failed(battery.id)
                found = {}
            for battery in missing:
                if battery.address not in found:
                    if battery.id not in self._retry_at or monotonic() >= self._retry_at[battery.id]:
                        try:
                            raise ConnectionError(f"Battery {battery.id} not discovered")
                        except ConnectionError:
                            self._failed(battery.id)
                    continue
                connection = BatteryConnection(found[battery.address], self._config.poller.timeout_seconds)
                try:
                    await connection.connect()
                    self._connections[battery.id] = connection
                    if self._active() and self._config.poller.persistent_connections:
                        self._persistent_ids.add(battery.id)
                        logger.info(
                            "Persistent BLE connection started for battery %s (%s)",
                            battery.id, battery.name,
                        )
                except BaseException as exc:
                    await connection.close()
                    if not isinstance(exc, Exception):
                        raise
                    self._failed(battery.id)
        semaphore = asyncio.Semaphore(self._config.poller.concurrency)
        await asyncio.gather(*(self._read(b, semaphore) for b in batteries if b.id in self._connections))

    async def run(self) -> None:
        due = monotonic()
        was_active = self._active()
        try:
            while True:
                self._wake.clear()
                now = monotonic()
                active = self._active()
                if was_active and not active:
                    due = now + self._config.poller.poll_interval_seconds
                was_active = active
                if not active:
                    for battery_id in list(self._connections):
                        await self._close(battery_id)
                if now >= due:
                    self._running = True
                    self._last_started = now
                    await self._pass()
                    self._running = False
                    interval = self._config.poller.active_interval_seconds if self._active() else self._config.poller.poll_interval_seconds
                    # Keep start cadence, skipping elapsed slots.
                    elapsed = monotonic() - now
                    due = now + (int(elapsed // interval) + 1) * interval
                delay = max(0, due - monotonic())
                if self._subscribers == 0 and self._active():
                    delay = min(delay, max(0, self._grace_until - monotonic()))
                try:
                    async with asyncio.timeout(delay):
                        await self._wake.wait()
                    if self._subscribers > 0 or self._grace_until == 0:
                        due = monotonic()
                except TimeoutError:
                    if not self._active() and self._connections:
                        for battery_id in list(self._connections):
                            await self._close(battery_id)
                        due = monotonic() + self._config.poller.poll_interval_seconds
        finally:
            self._stopped = True
            self._running = False
            for battery_id in list(self._connections):
                await self._close(battery_id)
