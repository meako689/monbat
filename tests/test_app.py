from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import monbat
import monbat.app as app_module
import monbat.poller as poller_module
from monbat.app import (
    AppConfig,
    BatteryConfig,
    PollerConfig,
    ServerConfig,
    _load_config,
    build_app,
)
from monbat.bms import BatteryTelemetry
from monbat.db import TelemetryRepository


class StubTelemetryRepository(TelemetryRepository):
    def __init__(
        self,
        latest: dict[str, BatteryTelemetry | None] | None = None,
        history: dict[str, list[BatteryTelemetry]] | None = None,
    ) -> None:
        self.latest = latest if latest is not None else {}
        self.history = history if history is not None else {}
        self.saved: list[tuple[str, BatteryTelemetry]] = []
        self.init_calls = 0
        self.history_cutoffs: dict[str, float] = {}

    async def init_db(self) -> None:
        self.init_calls += 1

    async def save_telemetry(
        self, battery_id: str, telemetry: BatteryTelemetry
    ) -> None:
        self.saved.append((battery_id, telemetry))

    async def get_latest_telemetry(
        self, battery_id: str
    ) -> BatteryTelemetry | None:
        return self.latest.get(battery_id)

    async def get_history(
        self, battery_id: str, since_timestamp: float
    ) -> list[BatteryTelemetry]:
        self.history_cutoffs[battery_id] = since_timestamp
        return list(self.history.get(battery_id, []))


def _make_config(
    batteries: tuple[BatteryConfig, ...] | None = None,
    *,
    poll_interval_seconds: float = 30.0,
) -> AppConfig:
    configured_batteries = batteries or (
        BatteryConfig("bat-1", "Battery 1", "AA:BB:CC:00:00:01"),
        BatteryConfig("bat-2", "Battery 2", "AA:BB:CC:00:00:02"),
    )
    return AppConfig(
        poller=PollerConfig(
            poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=10.0,
            sqlite_path="test.db",
        ),
        server=ServerConfig(host="127.0.0.1", port=8000),
        batteries=configured_batteries,
    )


def _make_telemetry(
    timestamp: float,
    *,
    current_a: float = 1.25,
    cell_voltages_v: tuple[float, ...] = (3.280, 3.282, 3.281),
) -> BatteryTelemetry:
    return BatteryTelemetry(
        timestamp=timestamp,
        voltage_v=26.25,
        current_a=current_a,
        power_w=round(26.25 * current_a, 2),
        soc_percent=50.0,
        remaining_ah=50.0,
        capacity_ah=100.0,
        cell_temp_c=24,
        bms_temp_c=25,
        cell_voltages_v=cell_voltages_v,
        reported_soc_percent=37.0,
        soc_source="bms",
        soh_percent=98.0,
        cycle_count=123,
        bms_state_raw=4,
        bms_state="disabled",
        protection_flags=4,
        active_protections=("Overcharge",),
    )


def test_latest_empty_includes_config_for_each_battery() -> None:
    repo = StubTelemetryRepository()
    app = build_app(_make_config(), repo, start_poller=False)

    with TestClient(app) as client:
        response = client.get("/api/latest")

    assert response.status_code == 200
    assert response.json() == {
        "bat-1": {
            "name": "Battery 1",
            "address": "AA:BB:CC:00:00:01",
            "telemetry": None,
            "status": "no-reading-yet",
            "cell_delta_mv": None,
        },
        "bat-2": {
            "name": "Battery 2",
            "address": "AA:BB:CC:00:00:02",
            "telemetry": None,
            "status": "no-reading-yet",
            "cell_delta_mv": None,
        },
    }
    assert repo.init_calls == 1


def test_latest_returns_telemetry_and_view_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module.time, "time", lambda: 1_000.0)
    telemetry = _make_telemetry(990.0, current_a=-2.0)
    repo = StubTelemetryRepository(latest={"bat-1": telemetry})
    app = build_app(_make_config(), repo, start_poller=False)

    with TestClient(app) as client:
        response = client.get("/api/latest")

    battery = response.json()["bat-1"]
    assert battery["name"] == "Battery 1"
    assert battery["address"] == "AA:BB:CC:00:00:01"
    assert battery["status"] == "discharging"
    assert battery["cell_delta_mv"] == 2.0
    assert battery["telemetry"]["current_a"] == -2.0
    assert battery["telemetry"]["bms_state"] == "disabled"
    assert battery["telemetry"]["protection_flags"] == 4
    assert battery["telemetry"]["active_protections"] == ["Overcharge"]
    assert battery["telemetry"]["cycle_count"] == 123
    assert battery["telemetry"]["soh_percent"] == 98
    assert battery["telemetry"]["reported_soc_percent"] == 37
    assert battery["telemetry"]["soc_source"] == "bms"
    assert battery["telemetry"]["cell_voltages_v"] == [3.28, 3.282, 3.281]


def test_latest_marks_stale_reading_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module.time, "time", lambda: 1_000.0)
    repo = StubTelemetryRepository(latest={"bat-1": _make_telemetry(939.0)})
    app = build_app(_make_config(), repo, start_poller=False)

    with TestClient(app) as client:
        response = client.get("/api/latest")

    assert response.json()["bat-1"]["status"] == "offline"


@pytest.mark.parametrize(
    ("current_a", "expected_status"),
    [(1.0, "charging"), (-1.0, "discharging"), (0.0, "idle")],
)
def test_latest_derives_fresh_status_from_current(
    monkeypatch: pytest.MonkeyPatch,
    current_a: float,
    expected_status: str,
) -> None:
    monkeypatch.setattr(app_module.time, "time", lambda: 1_000.0)
    repo = StubTelemetryRepository(
        latest={"bat-1": _make_telemetry(990.0, current_a=current_a)}
    )
    app = build_app(_make_config(), repo, start_poller=False)

    with TestClient(app) as client:
        response = client.get("/api/latest")

    assert response.json()["bat-1"]["status"] == expected_status


def test_history_returns_plain_chronological_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module.time, "time", lambda: 10_000.0)
    repo = StubTelemetryRepository(
        history={
            "bat-1": [_make_telemetry(9_000.0), _make_telemetry(7_000.0)],
            "bat-2": [_make_telemetry(8_000.0)],
        }
    )
    app = build_app(_make_config(), repo, start_poller=False)

    with TestClient(app) as client:
        response = client.get("/api/history?hours=24")

    rows = response.json()
    assert isinstance(rows, list)
    assert [row["timestamp"] for row in rows] == [7_000.0, 8_000.0, 9_000.0]
    assert [row["battery_id"] for row in rows] == ["bat-1", "bat-2", "bat-1"]
    assert rows[0]["bms_state"] == "disabled"
    assert rows[0]["active_protections"] == ["Overcharge"]
    assert rows[0]["cycle_count"] == 123
    assert rows[0]["name"] == "Battery 1"
    assert rows[0]["address"] == "AA:BB:CC:00:00:01"
    assert set(repo.history_cutoffs) == {"bat-1", "bat-2"}
    assert set(repo.history_cutoffs.values()) == {-76_400.0}


def test_history_is_empty_when_no_rows_match() -> None:
    repo = StubTelemetryRepository()
    app = build_app(_make_config(), repo, start_poller=False)

    with TestClient(app) as client:
        response = client.get("/api/history")

    assert response.status_code == 200
    assert response.json() == []


def test_history_rejects_non_positive_hours() -> None:
    app = build_app(_make_config(), StubTelemetryRepository(), start_poller=False)

    with TestClient(app) as client:
        response = client.get("/api/history?hours=0")

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("battery_address_fields", "expected_address"),
    [
        ('address = "AA:BB:CC:00:00:01"', "AA:BB:CC:00:00:01"),
        ('mac_address = "AA:BB:CC:00:00:02"', "AA:BB:CC:00:00:02"),
        (
            'address = "AA:BB:CC:00:00:03"\nmac_address = "AA:BB:CC:00:00:04"',
            "AA:BB:CC:00:00:03",
        ),
    ],
)
def test_load_config_supports_current_and_legacy_address_fields(
    tmp_path: Path,
    battery_address_fields: str,
    expected_address: str,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """[poller]
poll_interval_seconds = 30
timeout_seconds = 10.0
sqlite_path = "monbat.db"

[server]
host = "127.0.0.1"
port = 8000

[[batteries]]
id = "bat-1"
name = "Battery 1"
"""
        + battery_address_fields
        + "\n",
        encoding="utf-8",
    )

    config = _load_config(str(config_path))

    assert config.batteries[0].address == expected_address


def test_load_config_rejects_duplicate_battery_ids(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """[poller]
poll_interval_seconds = 30
timeout_seconds = 10.0
sqlite_path = "monbat.db"

[server]
host = "127.0.0.1"
port = 8000

[[batteries]]
id = "bat-1"
name = "Battery 1"
address = "AA:BB:CC:00:00:01"

[[batteries]]
id = "bat-1"
name = "Battery 2"
address = "AA:BB:CC:00:00:02"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate battery id"):
        _load_config(str(config_path))


def test_poller_continues_after_battery_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config = _make_config()
    previous = _make_telemetry(900.0)
    repo = StubTelemetryRepository(latest={"bat-1": previous})
    polled_addresses: list[str] = []
    telemetry = _make_telemetry(1_000.0)

    async def poll(address: str, timeout_seconds: float) -> BatteryTelemetry:
        polled_addresses.append(address)
        if address == config.batteries[0].address:
            raise TimeoutError("no response")
        return telemetry

    monkeypatch.setattr(poller_module, "poll_battery", poll)
    with caplog.at_level(logging.WARNING, logger="monbat.poller"):
        with TestClient(build_app(config, repo)) as client:
            for _ in range(100):
                client.get('/api/latest')
                if repo.saved:
                    break
            assert repo.saved == [("bat-2", telemetry)]
            retained = client.get('/api/latest').json()['bat-1']['telemetry']
            assert retained['timestamp'] == previous.timestamp

    assert polled_addresses == [
        "AA:BB:CC:00:00:01",
        "AA:BB:CC:00:00:02",
    ]
    assert "Poll failed for battery bat-1" in caplog.text


def test_dashboard_html_is_self_contained() -> None:
    app = build_app(_make_config(), StubTelemetryRepository(), start_poller=False)

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "setInterval(updateDashboard, 30000)" in response.text
    assert "updateDashboard();" in response.text
    assert "https://" not in response.text
    assert "http://" not in response.text


@pytest.mark.parametrize("arguments", [[], ["serve"]])
def test_main_dispatches_serve_for_default_and_subcommand(
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(sys, "argv", ["monbat", *arguments])
    monkeypatch.setattr(app_module, "serve", lambda: calls.append("serve"))

    monbat.main()

    assert calls == ["serve"]


@pytest.mark.parametrize("freshness", [0, -1, True, "60", float("inf"), float("nan")])
def test_invalid_freshness(freshness: object) -> None:
    raw = {
        "poller": {"poll_interval_seconds": 600, "timeout_seconds": 10,
                   "sqlite_path": "test.db", "freshness_seconds": freshness},
        "server": {"host": "localhost", "port": 8000},
        "batteries": [{"id": "one", "name": "One", "address": "one"}],
    }
    with pytest.raises(ValueError, match="freshness_seconds"):
        app_module._parse_config(raw)


def test_freshness_default_and_discovery() -> None:
    from monbat.discover import _serialize_config
    assert 'freshness_seconds = 60' in _serialize_config([])
    assert _make_config(poll_interval_seconds=600).poller.freshness_seconds == 60


@pytest.mark.parametrize("age,status", [(60, "charging"), (60.01, "offline")])
def test_freshness_independent_of_background(monkeypatch: pytest.MonkeyPatch, age: float, status: str) -> None:
    monkeypatch.setattr(app_module.time, "time", lambda: 1000)
    app = build_app(_make_config(poll_interval_seconds=600),
                    StubTelemetryRepository(latest={"bat-1": _make_telemetry(1000-age)}),
                    start_poller=False)
    with TestClient(app) as client:
        assert client.get('/api/latest').json()['bat-1']['status'] == status
        assert client.post('/api/refresh').json() == {"outcome": "disabled"}


def test_refresh_one_poller_and_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    clock = [100.0]
    monkeypatch.setattr(poller_module, "monotonic", lambda: clock[0])
    entered = threading.Event()
    release = threading.Event()
    cancelled = threading.Event()
    calls: list[str] = []
    active = 0
    max_active = 0

    async def poll(address: str, timeout: float) -> BatteryTelemetry:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        calls.append(address)
        entered.set()
        try:
            while not release.is_set():
                await asyncio.sleep(0)
            return _make_telemetry(1000)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        finally:
            active -= 1

    monkeypatch.setattr(poller_module, "poll_battery", poll)
    repo = StubTelemetryRepository()
    config = _make_config(poll_interval_seconds=600)
    app = build_app(config, repo)
    with TestClient(app) as client:
        assert entered.wait(2)
        assert client.post('/api/refresh').json()['outcome'] == 'skipped'
        assert client.get('/api/latest').status_code == 200
        release.set()
        # A request runs on the same event loop after the quick completed pass.
        for _ in range(100):
            client.get('/api/latest')
            if len(repo.saved) == 2:
                break
        assert len(repo.saved) == 2
        clock[0] = 129.99
        assert client.post('/api/refresh').json()['outcome'] == 'skipped'
        release.clear()
        entered.clear()
        clock[0] = 130
        assert client.post('/api/refresh').json()['outcome'] == 'accepted'
        assert entered.wait(2)
        assert client.post('/api/refresh').json()['outcome'] == 'skipped'
        assert calls == [_make_config().batteries[0].address,
                         _make_config().batteries[1].address,
                         _make_config().batteries[0].address]
    assert cancelled.is_set()
    assert max_active == 1


def test_refresh_atomic_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    from httpx2 import ASGITransport, AsyncClient

    clock = [0.0]
    monkeypatch.setattr(poller_module, "monotonic", lambda: clock[0])
    calls: list[str] = []
    entered = asyncio.Event()
    release = asyncio.Event()

    async def poll(address: str, timeout: float) -> BatteryTelemetry:
        calls.append(address)
        if len(calls) > 2:
            entered.set()
            await release.wait()
        return _make_telemetry(1000)

    monkeypatch.setattr(poller_module, "poll_battery", poll)
    repo = StubTelemetryRepository()
    config = _make_config(poll_interval_seconds=600)
    app = build_app(config, repo)

    async def scenario() -> None:
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test",
            ) as client:
                # Startup is reserved even before the task gets its first turn.
                assert (await client.post('/api/refresh')).json()['outcome'] == 'skipped'
                async with asyncio.timeout(2):
                    while len(repo.saved) < 2:
                        await asyncio.sleep(0)
                clock[0] = 30
                responses = await asyncio.gather(*(
                    client.post('/api/refresh') for _ in range(20)
                ))
                outcomes = [response.json()['outcome'] for response in responses]
                assert outcomes.count('accepted') == 1
                assert outcomes.count('skipped') == 19
                async with asyncio.timeout(2):
                    await entered.wait()
                addresses = [battery.address for battery in config.batteries]
                assert calls == addresses + [addresses[0]]
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            assert (await client.post('/api/refresh')).json()['outcome'] == 'disabled'

    asyncio.run(scenario())


def test_background_delay_restarts_after_refresh_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from httpx2 import ASGITransport, AsyncClient

    clock = [0.0]
    monkeypatch.setattr(poller_module, "monotonic", lambda: clock[0])
    calls = 0
    refresh_entered = asyncio.Event()
    release_refresh = asyncio.Event()
    background_entered = asyncio.Event()

    async def poll(address: str, timeout: float) -> BatteryTelemetry:
        nonlocal calls
        calls += 1
        if calls == 2:
            refresh_entered.set()
            await release_refresh.wait()
        if calls == 3:
            background_entered.set()
        return _make_telemetry(1000)

    monkeypatch.setattr(poller_module, "poll_battery", poll)
    config = _make_config(
        batteries=(BatteryConfig("one", "One", "one"),),
        poll_interval_seconds=0.1,
    )
    repo = StubTelemetryRepository()
    app = build_app(config, repo)

    async def scenario() -> None:
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app), base_url="http://test",
            ) as client:
                async with asyncio.timeout(2):
                    while not repo.saved:
                        await asyncio.sleep(0)
                clock[0] = 30
                assert (await client.post('/api/refresh')).json()['outcome'] == 'accepted'
                async with asyncio.timeout(2):
                    await refresh_entered.wait()
                # Let the original background deadline pass during BLE work.
                await asyncio.sleep(0.12)
                assert calls == 2
                release_refresh.set()
                async with asyncio.timeout(2):
                    while len(repo.saved) < 2:
                        await asyncio.sleep(0)
                with pytest.raises(TimeoutError):
                    async with asyncio.timeout(0.03):
                        await background_entered.wait()
                async with asyncio.timeout(2):
                    await background_entered.wait()
                assert calls == 3

    asyncio.run(scenario())


def test_background_polling_without_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    async def poll(address: str, timeout: float) -> BatteryTelemetry:
        nonlocal calls
        calls += 1
        return _make_telemetry(1000)
    monkeypatch.setattr(poller_module, "poll_battery", poll)
    config = _make_config(poll_interval_seconds=0.01)
    with TestClient(build_app(config, StubTelemetryRepository())) as client:
        import time
        deadline = time.perf_counter() + 2
        while calls < 4 and time.perf_counter() < deadline:
            client.get('/api/latest')
        assert calls >= 4


def test_bank_summary_weighted_soc_and_signed_power(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace
    monkeypatch.setattr(app_module.time, 'time', lambda: 1000)
    first = replace(_make_telemetry(990), soc_percent=80, capacity_ah=100, power_w=100)
    second = replace(_make_telemetry(990), soc_percent=20, capacity_ah=200, power_w=-300,
                     soc_source='capacity', reported_soc_percent=None)
    repo = StubTelemetryRepository(latest={'bat-1': first, 'bat-2': second})
    with TestClient(build_app(_make_config(), repo, start_poller=False)) as client:
        assert client.get('/api/summary').json() == {
            'available': True, 'soc_percent': 40, 'power_w': -200, 'reason': None,
        }
        assert set(client.get('/api/latest').json()) == {'bat-1', 'bat-2'}
        repo.latest['bat-2'] = replace(second, power_w=-100)
        assert client.get('/api/summary').json()['power_w'] == 0


@pytest.mark.parametrize('scenario,reason', [
    ('missing', 'missing-reading'), ('stale', 'stale-reading'),
    ('zero-capacity', 'invalid-capacity'), ('negative-capacity', 'invalid-capacity'),
])
def test_bank_summary_unavailable_and_recovers(monkeypatch: pytest.MonkeyPatch,
                                              scenario: str, reason: str) -> None:
    from dataclasses import replace
    monkeypatch.setattr(app_module.time, 'time', lambda: 1000)
    first = _make_telemetry(940)  # Exact freshness boundary remains available.
    second: BatteryTelemetry | None = _make_telemetry(940)
    if scenario == 'missing':
        second = None
    elif scenario == 'stale':
        second = _make_telemetry(939.99)
    else:
        second = replace(second, capacity_ah=0 if scenario == 'zero-capacity' else -1)
    repo = StubTelemetryRepository(latest={'bat-1': first, 'bat-2': second})
    with TestClient(build_app(_make_config(poll_interval_seconds=600), repo,
                              start_poller=False)) as client:
        assert client.get('/api/summary').json() == {
            'available': False, 'soc_percent': None, 'power_w': None, 'reason': reason,
        }
        repo.latest['bat-2'] = first
        result = client.get('/api/summary').json()
        assert result['available'] is True
        assert result['soc_percent'] == 50
        assert result['reason'] is None


def test_bank_summary_reason_precedence() -> None:
    from dataclasses import replace
    stale = replace(_make_telemetry(0), capacity_ah=0)
    assert app_module._bank_summary([None, stale], 60, 1000).reason == 'missing-reading'
    assert app_module._bank_summary([stale], 60, 1000).reason == 'stale-reading'


def test_summary_section_and_single_refresh_timer() -> None:
    with TestClient(build_app(_make_config(), StubTelemetryRepository(), start_poller=False)) as client:
        html = client.get('/').text
    assert html.index('id="bank-summary"') < html.index('id="batteries-grid"')
    assert "fetch('/api/summary')" in html
    assert html.count('setInterval(') == 1
    assert 'role="progressbar"' in html
