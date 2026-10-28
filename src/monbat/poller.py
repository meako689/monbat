"""Browser-aware collection with independently retained Battery connections."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING, Literal

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from monbat.bms import BatteryConnection, BatteryTelemetry
from monbat.db import TelemetryRepository

if TYPE_CHECKING:
    from monbat.app import AppConfig, BatteryConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _BatteryState:
    device: BLEDevice | None = None
    connection: BatteryConnection | None = None
    cleanup_pending: bool = False
    rediscover: bool = False
    failures: int = 0
    retry_at: float = 0.0
    persistent: bool = False


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
        self._batteries = {battery.id: _BatteryState() for battery in config.batteries}

    def subscribe(self) -> None:
        self._subscribers += 1
        logger.debug("[DEBUG-resume] Subscriber added count=%d", self._subscribers)
        if self._subscribers == 1:
            self._wake.set()
            logger.debug("[DEBUG-resume] Collection wake requested reason=first-subscriber")

    def unsubscribe(self) -> None:
        self._subscribers = max(0, self._subscribers - 1)
        logger.debug("[DEBUG-resume] Subscriber removed count=%d", self._subscribers)
        if self._subscribers == 0:
            self._grace_until = monotonic() + 30
            self._wake.set()
            logger.debug("[DEBUG-resume] Subscriber grace started until_monotonic=%.6f", self._grace_until)

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
        logger.debug("[DEBUG-resume] Collection wake requested reason=refresh")
        return "accepted"

    def _backoff(self, state: _BatteryState) -> None:
        state.retry_at = monotonic() + min(10 * 2 ** (max(1, state.failures) - 1), 60)

    def _failed(self, battery_id: str) -> None:
        state = self._batteries[battery_id]
        state.failures = min(state.failures + 1, 4)
        self._backoff(state)
        logger.debug(
            "[DEBUG-resume] Battery retry scheduled battery=%s failures=%d retry_at_monotonic=%.6f next=%s cleanup_pending=%s",
            battery_id, state.failures, state.retry_at,
            "discovery" if state.rediscover or state.device is None else "cached",
            state.cleanup_pending,
        )
        logger.warning("Poll failed for battery %s", battery_id, exc_info=True)

    async def _close(self, battery_id: str) -> bool:
        state = self._batteries[battery_id]
        connection = state.connection
        if connection is None:
            return True
        state.cleanup_pending = True
        started = monotonic()
        logger.debug("[DEBUG-resume] Cleanup started battery=%s timeout=%.3f", battery_id, self._config.poller.timeout_seconds)
        try:
            async with asyncio.timeout(self._config.poller.timeout_seconds):
                await connection.close()
        except Exception:
            # Cleanup retries must not count the original BLE failure again.
            state.failures = max(1, state.failures)
            self._backoff(state)
            logger.debug(
                "[DEBUG-resume] Cleanup deferred battery=%s elapsed=%.3f retry_at_monotonic=%.6f",
                battery_id, monotonic() - started, state.retry_at,
            )
            logger.warning("Disconnect failed for %s", battery_id, exc_info=True)
            return False
        state.connection = None
        state.cleanup_pending = False
        logger.debug("[DEBUG-resume] Cleanup completed battery=%s elapsed=%.3f", battery_id, monotonic() - started)
        if state.persistent:
            logger.info("Persistent BLE connection finished for battery %s", battery_id)
            state.persistent = False
        return True

    async def _save(self, battery_id: str, telemetry: BatteryTelemetry) -> None:
        logger.debug("[DEBUG-resume] Telemetry save started battery=%s timestamp=%.6f", battery_id, telemetry.timestamp)
        try:
            await self._repo.save_telemetry(battery_id, telemetry)
        except Exception:
            self._failed(battery_id)
            return
        state = self._batteries[battery_id]
        state.failures = 0
        state.retry_at = 0.0
        logger.debug("[DEBUG-resume] Telemetry saved battery=%s timestamp=%.6f backoff_cleared=true", battery_id, telemetry.timestamp)

    async def _read(self, battery: BatteryConfig, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            state = self._batteries[battery.id]
            connection = state.connection
            assert connection is not None
            logger.debug("[DEBUG-resume] Retained read started battery=%s", battery.id)
            try:
                telemetry = await connection.read()
            except Exception:
                state.cleanup_pending = True
                state.rediscover = False
                self._failed(battery.id)
                return
            await self._save(battery.id, telemetry)
            logger.debug("[DEBUG-resume] Retained read completed battery=%s", battery.id)

    async def _recover(
        self, battery: BatteryConfig, semaphore: asyncio.Semaphore, *, discovered: bool,
    ) -> None:
        async with semaphore:
            state = self._batteries[battery.id]
            assert state.device is not None and state.connection is None
            started = monotonic()
            logger.debug(
                "[DEBUG-resume] Recovery started battery=%s attempt=%s address=%s timeout=%.3f",
                battery.id, "discovered" if discovered else "cached",
                state.device.address, self._config.poller.timeout_seconds,
            )
            try:
                connection = BatteryConnection(state.device, self._config.poller.timeout_seconds)
                # Own partially connected/subscribed clients before any await.
                state.connection = connection
                state.cleanup_pending = True
                async with asyncio.timeout(self._config.poller.timeout_seconds):
                    await connection.connect()
                    logger.debug("[DEBUG-resume] Recovery connected and subscribed battery=%s", battery.id)
                    if self._active() and self._config.poller.persistent_connections:
                        state.persistent = True
                        logger.info(
                            "Persistent BLE connection started for battery %s (%s)",
                            battery.id, battery.name,
                        )
                    telemetry = await connection.read()
                    logger.debug("[DEBUG-resume] Recovery read completed battery=%s elapsed=%.3f", battery.id, monotonic() - started)
            except Exception:
                state.rediscover = not discovered
                self._failed(battery.id)
                await self._close(battery.id)
                return
            state.cleanup_pending = False
            state.rediscover = False
            await self._save(battery.id, telemetry)
            if not self._active() or not self._config.poller.persistent_connections:
                await self._close(battery.id)

    async def _pass(self) -> None:
        now = monotonic()
        batteries = [b for b in self._config.batteries if now >= self._batteries[b.id].retry_at]
        healthy = [b for b in batteries if self._batteries[b.id].connection is not None
                   and not self._batteries[b.id].cleanup_pending]
        recovering = [b for b in batteries if b not in healthy]
        logger.debug(
            "[DEBUG-resume] Collection pass started now_monotonic=%.6f active=%s subscribers=%d healthy=%s recovering=%s deferred=%s",
            now, self._active(), self._subscribers, [b.id for b in healthy],
            [b.id for b in recovering],
            [(b.id, self._batteries[b.id].retry_at) for b in self._config.batteries if b not in batteries],
        )
        semaphore = asyncio.Semaphore(self._config.poller.concurrency)
        await asyncio.gather(*(self._read(b, semaphore) for b in healthy))
        # Healthy reads finish before cleanup, discovery, or replacement setup.
        for battery in healthy:
            if (self._batteries[battery.id].cleanup_pending or not self._active()
                    or not self._config.poller.persistent_connections):
                await self._close(battery.id)
        ready: list[BatteryConfig] = []
        for battery in recovering:
            state = self._batteries[battery.id]
            if state.cleanup_pending and not await self._close(battery.id):
                continue
            ready.append(battery)
        direct = [b for b in ready if self._batteries[b.id].device is not None
                  and not self._batteries[b.id].rediscover]
        discovery = [b for b in ready if b not in direct]
        logger.debug("[DEBUG-resume] Recovery selection cached=%s discovery=%s", [b.id for b in direct], [b.id for b in discovery])
        await asyncio.gather(*(self._recover(b, semaphore, discovered=False) for b in direct))
        if not discovery:
            return
        try:
            logger.debug("[DEBUG-resume] Shared discovery started batteries=%s timeout=%.3f", [b.id for b in discovery], self._config.poller.timeout_seconds)
            # Discovery itself waits timeout_seconds for advertisements. Allow
            # one extra timeout budget for scanner startup and shutdown.
            async with asyncio.timeout(2 * self._config.poller.timeout_seconds):
                devices = await BleakScanner.discover(timeout=self._config.poller.timeout_seconds)
        except Exception:
            for battery in discovery:
                self._batteries[battery.id].rediscover = False
                self._failed(battery.id)
            return
        found = {device.address: device for device in devices}
        logger.debug("[DEBUG-resume] Shared discovery completed configured_found=%s", [b.id for b in self._config.batteries if b.address in found])
        for battery in self._config.batteries:
            if battery.address in found:
                self._batteries[battery.id].device = found[battery.address]
        discovered: list[BatteryConfig] = []
        for battery in discovery:
            if battery.address not in found:
                self._batteries[battery.id].rediscover = False
                try:
                    raise ConnectionError(f"Battery {battery.id} not discovered")
                except ConnectionError:
                    self._failed(battery.id)
                continue
            discovered.append(battery)
        await asyncio.gather(*(self._recover(b, semaphore, discovered=True) for b in discovered))

    async def run(self) -> None:
        due = monotonic()
        was_active = self._active()
        logger.debug(
            "[DEBUG-resume] Poller started active_interval=%.3f background_interval=%.3f timeout=%.3f concurrency=%d persistent=%s",
            self._config.poller.active_interval_seconds, self._config.poller.poll_interval_seconds,
            self._config.poller.timeout_seconds, self._config.poller.concurrency,
            self._config.poller.persistent_connections,
        )
        try:
            while True:
                self._wake.clear()
                now = monotonic()
                active = self._active()
                if was_active != active:
                    logger.debug("[DEBUG-resume] Collection mode changed active=%s subscribers=%d", active, self._subscribers)
                if was_active and not active:
                    due = now + self._config.poller.poll_interval_seconds
                    for battery_id, state in self._batteries.items():
                        if state.connection is not None and not state.cleanup_pending:
                            await self._close(battery_id)
                was_active = active
                if now >= due:
                    self._running = True
                    self._last_started = now
                    await self._pass()
                    logger.debug("[DEBUG-resume] Collection pass completed elapsed=%.3f", monotonic() - now)
                    self._running = False
                    interval = self._config.poller.active_interval_seconds if self._active() else self._config.poller.poll_interval_seconds
                    # Keep start cadence, skipping elapsed slots.
                    elapsed = monotonic() - now
                    due = now + (int(elapsed // interval) + 1) * interval
                delay = max(0, due - monotonic())
                if self._subscribers == 0 and self._active():
                    delay = min(delay, max(0, self._grace_until - monotonic()))
                try:
                    logger.debug("[DEBUG-resume] Scheduler waiting delay=%.3f due_monotonic=%.6f active=%s", delay, due, self._active())
                    async with asyncio.timeout(delay):
                        await self._wake.wait()
                    logger.debug("[DEBUG-resume] Scheduler woke reason=event subscribers=%d", self._subscribers)
                    if self._subscribers > 0 or self._grace_until == 0:
                        due = monotonic()
                except TimeoutError:
                    logger.debug("[DEBUG-resume] Scheduler woke reason=deadline")
                    pass
        finally:
            self._stopped = True
            logger.debug("[DEBUG-resume] Poller shutdown started")
            self._running = False
            for battery_id in self._batteries:
                await self._close(battery_id)
            logger.debug("[DEBUG-resume] Poller shutdown completed")
