"""Poller recovery behavior with real BLEDevice identities and controlled I/O."""
from __future__ import annotations

import asyncio
import errno
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from time import monotonic as real_monotonic

import pytest
from bleak.exc import BleakError
from bleak.backends.device import BLEDevice

from monbat import poller as module
from monbat.bluez import BlueZConnectionState
from monbat.bms import BatteryConnection, BatteryTelemetry
from monbat.poller import Poller
from test_app import _make_config, _make_telemetry, StubTelemetryRepository
from test_bms import REAL_STATUS


@dataclass
class Behavior:
    fail: str | None = None
    pause: str | None = None
    closes: list[str] = field(default_factory=list)


class Connection:
    def __init__(self, device: BLEDevice, rig: Rig, behavior: Behavior) -> None:
        self.device = device
        self.rig = rig
        self.behavior = behavior
        self.number = len(rig.clients)
        self.entered = asyncio.Event()
        self.close_count = 0
        rig.clients.append(self)

    async def step(self, stage: str) -> None:
        self.rig.events.append((self.number, stage))
        if self.behavior.pause == stage:
            self.entered.set()
            await asyncio.Event().wait()
        if self.behavior.fail == stage:
            raise OSError(f"device {self.device.address} not found: {stage}")

    async def connect(self) -> None:
        await self.step("connect")
        await self.step("notify")

    async def read(self) -> BatteryTelemetry:
        await self.step("read")
        return _make_telemetry(self.rig.clock + len(self.rig.repo.saved))

    async def close(self) -> None:
        self.close_count += 1
        await self.step("close")
        outcome = self.behavior.closes.pop(0) if self.behavior.closes else "ok"
        if outcome == "error":
            raise OSError("disconnect failed")
        if outcome == "timeout":
            await asyncio.Event().wait()


class Rig:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, active: bool = True) -> None:
        self.clock = 100.0
        self.config = _make_config()
        self.config = replace(self.config, poller=replace(self.config.poller, timeout_seconds=0.03))
        self.devices = [BLEDevice(b.address, b.name, {}) for b in self.config.batteries]
        self.scans: list[list[BLEDevice] | Exception] = []
        self.scan_count = 0
        self.clients: list[Connection] = []
        self.behaviors: list[Behavior] = []
        self.events: list[tuple[int, str]] = []
        self.repo = StubTelemetryRepository()
        self.poller = Poller(self.config, self.repo)
        if active:
            self.poller.subscribe()
        monkeypatch.setattr(module, "monotonic", lambda: self.clock)
        monkeypatch.setattr(module.BleakScanner, "discover", self.scan)
        monkeypatch.setattr(module, "BatteryConnection", self.connection)

        async def os_connection_state(
            address: str, timeout: float,
        ) -> BlueZConnectionState:
            return BlueZConnectionState.UNAVAILABLE

        async def disconnect_os_device(address: str, timeout: float) -> None:
            return None

        monkeypatch.setattr(module, "get_connection_state", os_connection_state, raising=False)
        monkeypatch.setattr(module, "disconnect_device", disconnect_os_device, raising=False)

    def connection(self, device: BLEDevice, timeout: float) -> Connection:
        assert isinstance(device, BLEDevice)
        behavior = self.behaviors.pop(0) if self.behaviors else Behavior()
        return Connection(device, self, behavior)

    async def scan(self, *, timeout: float) -> list[BLEDevice]:
        self.scan_count += 1
        self.events.append((-1, "scan"))
        result = self.scans.pop(0) if self.scans else self.devices
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.parametrize("active", [True, False])
def test_cached_reconnect_without_discovery(monkeypatch: pytest.MonkeyPatch, active: bool) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch, active=active)
        await rig.poller._pass()
        if active:
            rig.clients[0].behavior.fail = "read"
            await rig.poller._pass()
            rig.clock += 10
        rig.scans.append([])  # A new scan would miss both Batteries.
        await rig.poller._pass()
        assert rig.scan_count == 1
        replacement = rig.clients[2]
        assert replacement.device is rig.devices[0]
        assert rig.events.index((0, "close")) < rig.events.index((2, "connect"))
        assert (2, "notify") in rig.events and (2, "read") in rig.events
        assert any(battery == "bat-1" for battery, _ in rig.repo.saved[2:])
        if not active:
            assert all(client.close_count == 1 for client in rig.clients)
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["connect", "notify", "read"])
def test_cached_failure_defers_shared_discovery_and_refreshes_device(
    monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch, active=False)
        await rig.poller._pass()
        rig.behaviors.extend([Behavior(fail=failure), Behavior(fail=failure)])
        await rig.poller._pass()
        assert rig.scan_count == 1
        assert len(rig.repo.saved) == 2
        await rig.poller._pass()
        assert len(rig.clients) == 4  # Backoff prevents immediate attempts.
        fresh = [BLEDevice(d.address, d.name, {"path": "fresh"}) for d in rig.devices]
        rig.scans.append(fresh)
        rig.clock += 10
        await rig.poller._pass()
        assert rig.scan_count == 2
        assert len(rig.repo.saved) == 4
        assert rig.clients[4].device is fresh[0]
        assert rig.clients[5].device is fresh[1]
        assert all(client.close_count == 1 for client in rig.clients)
        assert all(state.failures == 0 for state in rig.poller._batteries.values())
    asyncio.run(scenario())


@pytest.mark.parametrize("scan_failure", [False, True])
def test_scan_miss_or_error_retains_cache_and_alternates_retries(
    monkeypatch: pytest.MonkeyPatch, scan_failure: bool,
) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch, active=False)
        await rig.poller._pass()
        rig.behaviors.extend([Behavior(fail="connect"), Behavior(fail="connect")])
        await rig.poller._pass()
        rig.scans.append(OSError("scan failed") if scan_failure else [])
        rig.clock += 10
        await rig.poller._pass()
        assert rig.scan_count == 2
        assert len(rig.clients) == 4
        assert all(state.failures == 2 for state in rig.poller._batteries.values())
        rig.clock += 20
        await rig.poller._pass()
        assert rig.scan_count == 2
        assert rig.clients[4].device is rig.devices[0]
        assert len(rig.repo.saved) == 4
    asyncio.run(scenario())


@pytest.mark.parametrize("scan_failure", [False, True])
def test_uncached_batteries_keep_discovering_after_backoff(
    monkeypatch: pytest.MonkeyPatch, scan_failure: bool,
) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch)
        rig.scans.append(OSError("scan failed") if scan_failure else [])
        await rig.poller._pass()
        await rig.poller._pass()
        assert rig.scan_count == 1 and not rig.clients
        assert all(state.failures == 1 for state in rig.poller._batteries.values())
        rig.clock += 10
        await rig.poller._pass()
        assert rig.scan_count == 2 and len(rig.repo.saved) == 2
    asyncio.run(scenario())


def test_discovery_refreshes_cache_for_ineligible_batteries(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch)
        rig.scans.append([rig.devices[0]])
        await rig.poller._pass()
        fresh = BLEDevice(rig.devices[0].address, "new", {"path": "new"})
        rig.poller._batteries["bat-1"].retry_at = 200
        rig.scans.append([fresh, rig.devices[1]])
        rig.clock += 10
        await rig.poller._pass()
        assert rig.poller._batteries["bat-1"].device is fresh
        assert rig.clients[0].device is rig.devices[0]  # Existing client remains usable.
    asyncio.run(scenario())


def test_healthy_reads_finish_before_cleanup_and_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch)
        await rig.poller._pass()
        rig.clients[0].behavior.fail = "read"
        rig.events.clear()
        await rig.poller._pass()
        assert rig.events.index((1, "read")) < rig.events.index((0, "close"))
        rig.clock += 10
        rig.behaviors.append(Behavior(fail="connect"))
        rig.events.clear()
        await rig.poller._pass()
        assert rig.events.index((1, "read")) < rig.events.index((2, "connect"))
        rig.clock += 20
        rig.events.clear()
        await rig.poller._pass()
        assert rig.events.index((1, "read")) < rig.events.index((-1, "scan"))
    asyncio.run(scenario())


@pytest.mark.parametrize("active", [True, False])
def test_database_failure_preserves_cache_and_ble_retry_kind(
    monkeypatch: pytest.MonkeyPatch, active: bool,
) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch, active=active)
        original_save = rig.repo.save_telemetry
        async def fail_save(battery_id: str, telemetry: BatteryTelemetry) -> None:
            raise OSError("database full")
        monkeypatch.setattr(rig.repo, "save_telemetry", fail_save)
        await rig.poller._pass()
        assert rig.scan_count == 1
        assert all(state.failures == 1 and not state.rediscover
                   for state in rig.poller._batteries.values())
        assert all(client.close_count == (0 if active else 1) for client in rig.clients)
        monkeypatch.setattr(rig.repo, "save_telemetry", original_save)
        rig.clock += 10
        await rig.poller._pass()
        assert rig.scan_count == 1 and len(rig.repo.saved) == 2
        assert len(rig.clients) == (2 if active else 4)
        assert all(state.failures == 0 for state in rig.poller._batteries.values())
    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["error", "timeout"])
def test_failed_cleanup_blocks_replacement_and_does_not_double_count(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, outcome: str,
) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch)
        await rig.poller._pass()
        old = rig.clients[0]
        old.behavior.fail = "read"
        old.behavior.closes = [outcome, outcome, "ok"]
        await rig.poller._pass()
        state = rig.poller._batteries["bat-1"]
        assert state.connection is old and state.cleanup_pending
        assert state.failures == 1
        await rig.poller._pass()
        assert old.close_count == 1
        rig.clock += 10
        await rig.poller._pass()
        assert old.close_count == 2 and len(rig.clients) == 2
        assert state.failures == 1
        rig.clock += 10
        await rig.poller._pass()
        assert old.close_count == 3 and len(rig.clients) == 3
        assert state.failures == 0
        assert "Disconnect failed for bat-1" in caplog.text
    asyncio.run(scenario())


def test_background_cleanup_failure_blocks_next_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch, active=False)
        rig.behaviors.append(Behavior(closes=["error", "ok"]))
        await rig.poller._pass()
        await rig.poller._pass()
        assert len(rig.clients) == 3  # Only bat-2 is eligible.
        rig.clock += 10
        await rig.poller._pass()
        assert rig.clients[0].close_count == 2
        assert rig.events.index((0, "close")) < rig.events.index((3, "connect"))
        assert rig.scan_count == 1
    asyncio.run(scenario())


def test_backoff_progression_and_no_reset_before_save(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch, active=False)
        rig.behaviors.extend([Behavior(fail="connect") for _ in range(10)])
        for delay in [10, 20, 40, 60, 60]:
            await rig.poller._pass()
            state = rig.poller._batteries["bat-1"]
            assert state.retry_at == rig.clock + delay
            attempts = len(rig.clients)
            rig.clock += delay - 1
            await rig.poller._pass()
            assert len(rig.clients) == attempts
            rig.clock += 1
        assert rig.scan_count == 3  # Discovery, direct, discovery, direct, discovery.
        await rig.poller._pass()
        assert all(state.failures == 0 and state.retry_at == 0
                   for state in rig.poller._batteries.values())
    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["connect", "notify", "read", "close"])
def test_cancellation_tracks_clients_and_shutdown_is_bounded(
    monkeypatch: pytest.MonkeyPatch, stage: str,
) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch, active=stage != "close")
        rig.behaviors.extend([Behavior(pause=stage), Behavior()])
        task = asyncio.create_task(rig.poller.run())
        while not rig.clients:
            await asyncio.sleep(0)
        client = rig.clients[0]
        await asyncio.wait_for(client.entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert client.close_count == (2 if stage == "close" else 1)
        assert all(c.close_count >= 1 for c in rig.clients)
        assert rig.poller.request_refresh() == "disabled"
    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", ["error", "timeout"])
def test_shutdown_retries_failed_setup_cleanup_once(
    monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch)
        rig.behaviors.append(Behavior(fail="notify", closes=[outcome, outcome]))
        task = asyncio.create_task(rig.poller.run())
        while rig.poller._running:
            await asyncio.sleep(0.001)
        assert rig.clients[0].close_count == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert rig.clients[0].close_count == 2
        assert rig.clients[1].close_count == 1
    asyncio.run(scenario())


def test_grace_cleanup_retains_cache_and_restart_requires_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch)
        await rig.poller._pass()
        rig.poller.unsubscribe()
        rig.clock += 31
        await rig.poller._pass()
        assert all(c.close_count == 1 for c in rig.clients)
        await rig.poller._pass()
        assert rig.scan_count == 1
        restarted = Poller(rig.config, rig.repo)
        await restarted._pass()
        assert rig.scan_count == 2
    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["connect", "notify", "read"])
def test_recovery_timeout_cleans_up_and_defers_discovery(
    monkeypatch: pytest.MonkeyPatch, stage: str,
) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch, active=False)
        await rig.poller._pass()
        rig.behaviors.append(Behavior(pause=stage))
        await asyncio.wait_for(rig.poller._pass(), 1)
        assert rig.clients[2].close_count == 1 and rig.scan_count == 1
        assert rig.poller._batteries["bat-1"].rediscover
        rig.clock += 10
        await rig.poller._pass()
        assert rig.scan_count == 2
    asyncio.run(scenario())


def test_scan_duration_allows_backend_cleanup_but_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch)
        async def scan(*, timeout: float) -> list[BLEDevice]:
            await asyncio.sleep(timeout)
            await asyncio.sleep(0)
            return rig.devices
        monkeypatch.setattr(module.BleakScanner, "discover", scan)
        await rig.poller._pass()
        assert len(rig.repo.saved) == 2
        other = Poller(rig.config, rig.repo)
        async def stalled_scan(*, timeout: float) -> list[BLEDevice]:
            await asyncio.Event().wait()
            return []
        monkeypatch.setattr(module.BleakScanner, "discover", stalled_scan)
        await asyncio.wait_for(other._pass(), 1)
        assert all(state.failures == 1 for state in other._batteries.values())
    asyncio.run(scenario())


def test_replacement_driver_subscribes_and_saves_its_own_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bleak
    from monbat.bms import BatteryConnection

    async def scenario() -> None:
        rig = Rig(monkeypatch)
        rig.config = replace(rig.config, batteries=(rig.config.batteries[0],))
        rig.poller = Poller(rig.config, rig.repo)
        rig.poller.subscribe()
        monkeypatch.setattr(module, "BatteryConnection", BatteryConnection)
        clients: list[Client] = []
        events: list[tuple[int, str]] = []

        class Client:
            callback: Callable[[object, bytearray], None]

            def __init__(self, device: BLEDevice, *, timeout: float) -> None:
                self.number = len(clients)
                self.reads = 0
                clients.append(self)

            async def connect(self) -> None:
                events.append((self.number, "connect"))

            async def start_notify(
                self, uuid: str, callback: Callable[[object, bytearray], None],
            ) -> None:
                self.callback = callback
                events.append((self.number, "notify"))
                callback(0, bytearray(REAL_STATUS))  # Unsolicited data before a request.

            async def write_gatt_char(self, uuid: str, data: bytes, *, response: bool) -> None:
                self.reads += 1
                if self.number == 0 and self.reads == 2:
                    raise OSError("link lost")
                frame = bytearray(REAL_STATUS)
                if self.number:
                    clients[0].callback(0, bytearray(REAL_STATUS))  # Old subscription data.
                    frame[90:92] = (42).to_bytes(2, "little")
                    frame[-1] = sum(frame[:-1]) & 0xff
                for start in range(0, len(frame), 20):
                    self.callback(0, frame[start:start + 20])

            async def disconnect(self) -> None:
                events.append((self.number, "disconnect"))

        monkeypatch.setattr(bleak, "BleakClient", Client)
        await rig.poller._pass()
        await rig.poller._pass()
        rig.clock += 10
        await rig.poller._pass()
        assert [telemetry.soc_percent for _, telemetry in rig.repo.saved] == [99, 42]
        assert events.index((0, "disconnect")) < events.index((1, "connect"))
        assert (1, "notify") in events and rig.scan_count == 1
        await rig.poller._close("bat-1")
    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("os_state", "replacement_attempt", "needs_rediscovery"),
    [
        (BlueZConnectionState.DISCONNECTED, 2, False),
        (BlueZConnectionState.ABSENT, 3, True),
    ],
)
def test_available_battery_recovers_after_setup_timeout_and_bad_fd_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    os_state: BlueZConnectionState,
    replacement_attempt: int,
    needs_rediscovery: bool,
) -> None:
    import bleak

    async def scenario() -> None:
        caplog.set_level("INFO", logger="monbat.poller")
        rig = Rig(monkeypatch, active=False)
        first_address = rig.config.batteries[0].address
        clients: list[Client] = []
        attempts: dict[str, int] = {}
        os_checks: list[str] = []

        class Client:
            def __init__(self, device: BLEDevice, *, timeout: float) -> None:
                self.address = device.address
                self.attempt = attempts.get(self.address, 0) + 1
                attempts[self.address] = self.attempt
                self.callback: Callable[[object, bytearray], None] | None = None
                self.disconnect_count = 0
                self.write_count = 0
                clients.append(self)

            async def connect(self) -> None:
                if self.address == first_address and self.attempt == 1:
                    raise TimeoutError("service discovery timeout")
                if (
                    os_state is BlueZConnectionState.ABSENT
                    and self.address == first_address
                    and self.attempt == 2
                ):
                    raise BleakError(f"device '{self.address}' not found")

            async def start_notify(
                self, uuid: str, callback: Callable[[object, bytearray], None],
            ) -> None:
                self.callback = callback

            async def write_gatt_char(
                self, uuid: str, data: bytes, *, response: bool,
            ) -> None:
                self.write_count += 1
                assert self.callback is not None
                self.callback(0, bytearray(REAL_STATUS))

            async def disconnect(self) -> None:
                self.disconnect_count += 1
                if self.address == first_address and self.attempt == 1:
                    raise OSError(errno.EBADF, "Bad file descriptor")

        async def inspect_os_connection(
            address: str, timeout: float,
        ) -> BlueZConnectionState:
            os_checks.append(address)
            return os_state

        monkeypatch.setattr(bleak, "BleakClient", Client)
        monkeypatch.setattr(module, "BatteryConnection", BatteryConnection)
        # Fake the independent OS-state boundary without touching BlueZ.
        monkeypatch.setattr(
            module, "get_connection_state", inspect_os_connection, raising=False,
        )

        await rig.poller._pass()
        saved = [battery_id for battery_id, _ in rig.repo.saved]
        assert saved.count("bat-1") == 0
        assert saved.count("bat-2") == 1
        assert clients[0].disconnect_count == 1

        if needs_rediscovery:
            rig.scans.append([
                BLEDevice(device.address, device.name, {"path": "refreshed"})
                for device in rig.devices
            ])
        rig.clock += 10
        await rig.poller._pass()

        saved = [battery_id for battery_id, _ in rig.repo.saved]
        assert saved.count("bat-1") == (0 if needs_rediscovery else 1)
        assert saved.count("bat-2") == 2
        if needs_rediscovery:
            rig.clock += 20
            await rig.poller._pass()
            saved = [battery_id for battery_id, _ in rig.repo.saved]
            assert saved.count("bat-1") == 1
            assert saved.count("bat-2") == 3
            assert rig.scan_count == 2
        else:
            assert rig.scan_count == 1
        replacement = next(
            client for client in clients
            if client.address == first_address and client.attempt == replacement_attempt
        )
        assert replacement.write_count == 1
        assert replacement.callback is not None
        assert clients[0].disconnect_count == 1
        assert os_checks == [first_address]
        if needs_rediscovery:
            assert any(
                record.levelno >= 30 and "remains unavailable" in record.getMessage()
                for record in caplog.records
            )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("os_states", "disconnect_error", "released", "disconnect_requests"),
    [
        ([BlueZConnectionState.DISCONNECTED], False, True, 0),
        ([BlueZConnectionState.ABSENT], False, True, 0),
        ([BlueZConnectionState.CONNECTED, BlueZConnectionState.DISCONNECTED], False, True, 1),
        ([BlueZConnectionState.CONNECTED, BlueZConnectionState.CONNECTED], True, False, 1),
        ([BlueZConnectionState.UNAVAILABLE], False, False, 0),
    ],
)
def test_cleanup_retires_client_only_after_os_release_is_confirmed(
    monkeypatch: pytest.MonkeyPatch,
    os_states: list[BlueZConnectionState],
    disconnect_error: bool,
    released: bool,
    disconnect_requests: int,
) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch)
        await rig.poller._pass()
        state = rig.poller._batteries["bat-1"]
        old = state.connection
        assert old is not None
        old.behavior.fail = "read"
        old.behavior.closes = ["error"]

        observed_states: list[BlueZConnectionState] = []
        requests: list[str] = []

        async def inspect_os_connection(
            address: str, timeout: float,
        ) -> BlueZConnectionState:
            index = min(len(observed_states), len(os_states) - 1)
            status = os_states[index]
            observed_states.append(status)
            return status

        async def request_os_disconnect(address: str, timeout: float) -> None:
            requests.append(address)
            if disconnect_error:
                raise TimeoutError("BlueZ disconnect timed out")

        monkeypatch.setattr(module, "get_connection_state", inspect_os_connection)
        monkeypatch.setattr(module, "disconnect_device", request_os_disconnect)

        await rig.poller._pass()

        assert len(requests) == disconnect_requests
        assert len(rig.clients) == 2
        assert len(observed_states) == len(os_states)
        assert (state.connection is None) is released
        assert state.cleanup_pending is not released
        saved = [battery_id for battery_id, _ in rig.repo.saved]
        assert saved.count("bat-1") == 1
        assert saved.count("bat-2") == 2

    asyncio.run(scenario())


def test_cleanup_retries_unavailable_os_check_until_release_is_observable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch)
        await rig.poller._pass()
        state = rig.poller._batteries["bat-1"]
        old = state.connection
        assert old is not None
        old.behavior.fail = "read"
        old.behavior.closes = ["error", "error"]
        statuses = iter([
            BlueZConnectionState.UNAVAILABLE,
            BlueZConnectionState.DISCONNECTED,
        ])

        async def inspect_os_connection(
            address: str, timeout: float,
        ) -> BlueZConnectionState:
            return next(statuses)

        monkeypatch.setattr(module, "get_connection_state", inspect_os_connection)
        await rig.poller._pass()
        assert state.connection is old
        assert state.cleanup_pending
        assert old.close_count == 1
        rig.clock += 10
        await rig.poller._pass()
        assert old.close_count == 2
        assert state.connection is not None and state.connection is not old
        assert not state.cleanup_pending
        assert len(rig.clients) == 3
        saved = [battery_id for battery_id, _ in rig.repo.saved]
        assert saved.count("bat-1") == 2
        assert saved.count("bat-2") == 3

    asyncio.run(scenario())


def test_connected_device_is_released_before_battery_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch)
        await rig.poller._pass()
        old = rig.poller._batteries["bat-1"].connection
        assert old is not None
        old.behavior.fail = "read"
        old.behavior.closes = ["error"]
        states = iter([
            BlueZConnectionState.CONNECTED,
            BlueZConnectionState.DISCONNECTED,
        ])
        os_events: list[str] = []

        async def inspect_os_connection(
            address: str, timeout: float,
        ) -> BlueZConnectionState:
            status = next(states)
            os_events.append(f"confirmed:{status.value}")
            rig.events.append((-2, f"confirmed:{status.value}"))
            return status

        async def request_os_disconnect(address: str, timeout: float) -> None:
            os_events.append("disconnect-requested")
            rig.events.append((-2, "disconnect-requested"))

        monkeypatch.setattr(module, "get_connection_state", inspect_os_connection)
        monkeypatch.setattr(module, "disconnect_device", request_os_disconnect)

        await rig.poller._pass()
        assert len(rig.clients) == 2
        assert rig.poller._batteries["bat-1"].connection is None
        assert os_events == [
            "confirmed:connected",
            "disconnect-requested",
            "confirmed:disconnected",
        ]

        rig.clock += 10
        await rig.poller._pass()
        replacement = rig.clients[2]
        assert replacement.device is rig.devices[0]
        assert rig.events.index((-2, "confirmed:disconnected")) < rig.events.index(
            (replacement.number, "connect")
        )
        assert [battery_id for battery_id, _ in rig.repo.saved].count("bat-1") == 2

    asyncio.run(scenario())


def test_transient_original_cleanup_failure_does_not_force_discard_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch)
        await rig.poller._pass()
        state = rig.poller._batteries["bat-1"]
        old = state.connection
        assert old is not None
        old.behavior.fail = "read"
        old.behavior.closes = ["error", "ok"]
        os_checks = 0

        async def inspect_connected(
            address: str, timeout: float,
        ) -> BlueZConnectionState:
            nonlocal os_checks
            os_checks += 1
            return BlueZConnectionState.CONNECTED

        async def failed_os_disconnect(address: str, timeout: float) -> None:
            raise TimeoutError("BlueZ disconnect timed out")

        monkeypatch.setattr(module, "get_connection_state", inspect_connected)
        monkeypatch.setattr(module, "disconnect_device", failed_os_disconnect)

        await rig.poller._pass()
        assert state.connection is old and state.cleanup_pending
        assert len(rig.clients) == 2
        assert os_checks == 2
        rig.clock += 10
        await rig.poller._pass()
        assert old.close_count == 2
        assert state.connection is not None and state.connection is not old
        assert not state.cleanup_pending
        assert os_checks == 2
        assert len(rig.clients) == 3

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("background_interval", "retry_delay"),
    [(1800.0, 0.02), (0.5, 0.2)],
)
def test_background_retry_wakes_only_failed_battery_and_keeps_collection_cadence(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    background_interval: float,
    retry_delay: float,
) -> None:
    async def scenario() -> None:
        caplog.set_level("DEBUG", logger="monbat.poller")
        rig = Rig(monkeypatch, active=False)
        config = replace(
            rig.config,
            poller=replace(
                rig.config.poller,
                poll_interval_seconds=background_interval,
            ),
        )
        rig.config = config
        rig.poller = Poller(config, rig.repo)
        monkeypatch.setattr(module, "monotonic", real_monotonic)

        first_address = config.batteries[0].address
        stale_devices: set[int] = set()
        base_factory = rig.connection
        read_times: dict[str, list[float]] = {b.address: [] for b in config.batteries}

        def connection(device: BLEDevice, timeout: float) -> Connection:
            client = base_factory(device, timeout)
            original_connect = client.connect
            original_read = client.read
            original_close = client.close

            async def connect() -> None:
                if id(device) in stale_devices:
                    raise BleakError(f"device '{device.address}' not found")
                await original_connect()

            async def read() -> BatteryTelemetry:
                read_times[device.address].append(real_monotonic())
                return await original_read()

            async def close() -> None:
                await original_close()
                if device.address == first_address:
                    stale_devices.add(id(device))

            client.connect = connect
            client.read = read
            client.close = close
            return client

        monkeypatch.setattr(module, "BatteryConnection", connection)

        # Save a normal background pass, then let BlueZ expire only bat-1's
        # cached object before the next scheduled collection.
        await rig.poller._pass()
        fresh_devices = [
            BLEDevice(device.address, device.name, {"path": "refreshed"})
            for device in rig.devices
        ]
        rig.scans.append(fresh_devices)

        def short_backoff(_poller: Poller, state: object) -> None:
            setattr(state, "retry_at", real_monotonic() + retry_delay)

        monkeypatch.setattr(Poller, "_backoff", short_backoff)
        run_started = real_monotonic()
        task = asyncio.create_task(rig.poller.run())

        async def wait_for_reads(address: str, count: int) -> None:
            while len(read_times[address]) < count:
                await asyncio.sleep(0.001)

        try:
            await asyncio.wait_for(wait_for_reads(first_address, 2), 0.5)
            other_address = next(b.address for b in config.batteries if b.address != first_address)
            assert len(read_times[other_address]) == 2
            assert rig.scan_count == 2

            if background_interval < 1:
                cadence_deadline = run_started + background_interval + 0.1
                remaining = max(0.0, cadence_deadline - real_monotonic())
                await asyncio.wait_for(wait_for_reads(other_address, 3), remaining)
                assert read_times[other_address][2] < cadence_deadline
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)

        saved = [battery_id for battery_id, _ in rig.repo.saved]
        assert saved.count("bat-1") >= 2
        assert saved.count("bat-2") == (3 if background_interval < 1 else 2)
        messages = [record.getMessage() for record in caplog.records]
        assert any("BlueZ device object missing for bat-1" in message for message in messages)
        assert any(
            "Background collection completed retry_only=True saved=bat-1" in message
            for message in messages
        )
        assert not any(
            record.levelno >= 30 and record.getMessage() == "Poll failed for battery bat-1"
            for record in caplog.records
        )
        assert any("[DEBUG-resume] Recovery started" in message for message in messages)

    asyncio.run(scenario())


def test_inactive_wakes_do_not_retry_failed_grace_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        rig = Rig(monkeypatch)
        rig.behaviors.append(Behavior(closes=["error", "ok"]))
        task = asyncio.create_task(rig.poller.run())
        try:
            while rig.poller._running:
                await asyncio.sleep(0.001)
            rig.poller.unsubscribe()
            rig.clock += 31
            rig.poller._wake.set()
            await asyncio.sleep(0.01)
            assert rig.clients[0].close_count == 1
            for _ in range(3):
                rig.poller._wake.set()
                await asyncio.sleep(0.001)
            assert rig.clients[0].close_count == 1
            assert len(rig.clients) == 2
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
        assert rig.clients[0].close_count == 2
    asyncio.run(scenario())
