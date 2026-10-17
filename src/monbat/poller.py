"""Sequential Battery polling and Dashboard refresh admission."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic
from typing import TYPE_CHECKING, Literal

from monbat.bms import poll_battery
from monbat.db import TelemetryRepository

if TYPE_CHECKING:
    from monbat.app import AppConfig

logger = logging.getLogger(__name__)


class Poller:
    """Own scheduling state for one lifespan-managed polling task."""

    def __init__(self, config: AppConfig, repo: TelemetryRepository) -> None:
        self._config = config
        self._repo = repo
        self._wake = asyncio.Event()
        self._running = True  # Reserve the startup pass before the task runs.
        self._stopped = False
        self._last_started: float | None = None

    def request_refresh(self) -> Literal["accepted", "skipped", "disabled"]:
        # No await: checking and reserving are atomic on the app event loop.
        if self._stopped:
            return "disabled"
        if self._running or self._wake.is_set():
            return "skipped"
        if self._last_started is not None and monotonic() - self._last_started < 30:
            return "skipped"
        self._wake.set()
        return "accepted"

    async def run(self) -> None:
        """Run once as a task; cancellation disables further refresh requests."""
        try:
            while True:
                self._running = True
                self._wake.clear()
                self._last_started = monotonic()
                for battery in self._config.batteries:
                    try:
                        telemetry = await poll_battery(
                            battery.address, self._config.poller.timeout_seconds
                        )
                        await self._repo.save_telemetry(battery.id, telemetry)
                    except Exception as exc:
                        logger.warning(
                            "Poll failed for battery %s: %s", battery.id, exc,
                            exc_info=True,
                        )
                self._running = False
                try:
                    async with asyncio.timeout(self._config.poller.poll_interval_seconds):
                        await self._wake.wait()
                except TimeoutError:
                    pass
        finally:
            self._stopped = True
            self._running = False
            self._wake.clear()
