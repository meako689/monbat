from __future__ import annotations

import asyncio
import json
import logging
import struct
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from playwright.async_api import Page, Route, expect, async_playwright

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
from protocol_fixtures import (
    REAL_STATUS,
    captured_status_frame,
    checksum_correct_status_frame,
)


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
    from monbat.bms import parse_bms_payload

    frame = captured_status_frame()
    frame[16:48] = bytes(32)
    for index, voltage in enumerate(cell_voltages_v):
        struct.pack_into("<H", frame, 16 + index * 2, round(voltage * 1000))
    struct.pack_into("<H", frame, 12, 26_250)
    struct.pack_into("<i", frame, 48, round(current_a * 1000))
    struct.pack_into("<5h", frame, 52, 24, 25, 0, 0, 0)
    struct.pack_into("<H", frame, 62, 5_000)
    struct.pack_into("<I", frame, 64, 10_000)
    struct.pack_into("<Q", frame, 76, 4)
    struct.pack_into("<H", frame, 88, 4)
    struct.pack_into("<H", frame, 90, 37)
    struct.pack_into("<I", frame, 92, 98)
    struct.pack_into("<I", frame, 96, 123)
    return parse_bms_payload(
        checksum_correct_status_frame(frame), timestamp=timestamp
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


def test_captured_protocol_fields_round_trip_through_sqlite_api_and_sse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from monbat.bms import parse_bms_payload

    original_telemetry = parse_bms_payload(REAL_STATUS, timestamp=989.0)
    frame = captured_status_frame()
    frame[16:48] = bytes(32)
    struct.pack_into("<H", frame, 16, 3300)
    struct.pack_into("<H", frame, 20, 3350)
    struct.pack_into("<5h", frame, 52, -24, 0, -32768, 0, 32767)
    struct.pack_into("<Q", frame, 76, 0x8000000180000004)
    struct.pack_into("<I", frame, 84, 0x80008005)
    struct.pack_into("<H", frame, 12, 26_240)
    struct.pack_into("<i", frame, 48, -1_250)
    captured_variant = checksum_correct_status_frame(frame)
    telemetry = parse_bms_payload(
        b"stale-prefix" + captured_variant + b"trailing-data", timestamp=990.0
    )

    high_word_only = bytearray(captured_variant)
    struct.pack_into("<Q", high_word_only, 76, 0x8000000000000000)
    high_word_variant = checksum_correct_status_frame(high_word_only)
    high_word_telemetry = parse_bms_payload(high_word_variant, timestamp=991.0)

    path = tmp_path / "telemetry.sqlite3"
    repo = TelemetryRepository(str(path))
    asyncio.run(repo.init_db())
    asyncio.run(repo.save_telemetry("bat-1", original_telemetry))
    asyncio.run(repo.save_telemetry("bat-1", telemetry))
    asyncio.run(repo.save_telemetry("bat-1", high_word_telemetry))
    monkeypatch.setattr(app_module.time, "time", lambda: 1_000.0)
    config = _make_config(
        batteries=(BatteryConfig("bat-1", "Battery 1", "synthetic-device"),)
    )
    app = build_app(config, repo, start_poller=False)

    with TestClient(app) as client:
        latest_response = client.get("/api/latest")
        history_response = client.get("/api/history?hours=24")
        assert latest_response.status_code == 200
        assert history_response.status_code == 200

        latest = latest_response.json()["bat-1"]["telemetry"]
        original_capture, first, latest_history = history_response.json()
        assert original_capture["timestamp"] == 989.0
        assert original_capture["raw_response_hex"] == REAL_STATUS.hex()
        assert latest_response.json()["bat-1"]["cell_delta_mv"] == 50.0
        assert first["cell_readings"] == [
            {"slot": 1, "voltage_v": 3.3},
            {"slot": 3, "voltage_v": 3.35},
        ]
        assert first["cell_voltages_v"] == [3.3, 3.35]
        assert first["temperature_slots_c"] == [-24, 0, -32768, 0, 32767]
        assert first["balancing_mask"] == 0x80008005
        assert first["balancing_cell_slots"] == [1, 3, 16]
        assert first["problem_flags"] == "8000000180000004"
        assert first["protection_flags"] == 0x80000004
        assert first["raw_response_hex"] == captured_variant.hex()
        assert latest_history["problem_flags"] == "8000000000000000"
        assert latest_history["protection_flags"] == 0
        assert latest_history["active_protections"] == []
        assert latest_history["raw_response_hex"] == high_word_telemetry.raw_response.hex()
        assert latest["problem_flags"] == "8000000000000000"
        assert latest["balancing_mask"] == 0x80008005
        assert "raw_response" not in latest
        assert "raw_response_hex" not in latest

        events_endpoint = next(
            route.endpoint
            for route in app.routes
            if isinstance(route, APIRoute) and route.path == "/api/events"
        )

        async def read_first_event() -> dict[str, object]:
            response = await events_endpoint()
            stream = response.body_iterator
            try:
                data_line = await anext(stream)
            finally:
                await stream.aclose()
            return json.loads(data_line.removeprefix("data: "))

        event = asyncio.run(read_first_event())
        assert isinstance(event, dict)
        latest_by_battery = event["latest"]
        assert isinstance(latest_by_battery, dict)
        event_battery = latest_by_battery["bat-1"]
        assert isinstance(event_battery, dict)
        event_latest = event_battery["telemetry"]
        assert isinstance(event_latest, dict)
        assert event_latest == latest
        assert "raw_response" not in event_latest
        assert "raw_response_hex" not in event_latest
        summary = event["summary"]
        assert isinstance(summary, dict)
        assert summary["power_w"] == -32.8


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


def test_dashboard_html_is_self_contained() -> None:
    app = build_app(_make_config(), StubTelemetryRepository(), start_poller=False)

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "new EventSource('/api/events')" in response.text
    assert "events.onmessage" in response.text
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
        assert result['soc_percent'] == 37
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
    assert html.count('new EventSource(') == 1
    assert 'role="progressbar"' in html


@asynccontextmanager
async def _browser_page() -> AsyncGenerator[Page, None]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            yield await browser.new_page()
        finally:
            await browser.close()


@pytest.mark.parametrize("has_telemetry", [False, True])
def test_dashboard_renders_config_labels_literally(
    has_telemetry: bool,
) -> None:
    async def scenario() -> None:
        async with _browser_page() as browser_page:
            name = '<img src=x onerror="window.injected=true"> & "Battery"'
            address = '</div><script>window.injected=true</script><svg onload="window.injected=true">'
            config = _make_config(batteries=(BatteryConfig('one', name, address),))
            repo = StubTelemetryRepository(
                latest={'one': _make_telemetry(1000) if has_telemetry else None},
            )

            with TestClient(build_app(config, repo, start_poller=False)) as client:
                async def serve(route: Route) -> None:
                    if route.request.url.endswith('/api/events'):
                        import json
                        snapshot = {'latest': client.get('/api/latest').json(), 'summary': client.get('/api/summary').json()}
                        await route.fulfill(status=200, body=f"data: {json.dumps(snapshot)}\n\n", content_type='text/event-stream')
                        return
                    response = client.request(route.request.method, route.request.url)
                    await route.fulfill(
                        status=response.status_code, body=response.content,
                        content_type=response.headers['content-type'],
                    )

                await browser_page.route('http://monbat.test/**', serve)
                await browser_page.goto('http://monbat.test/')
                await expect(browser_page.locator('#batteries-grid .card-title')).to_have_text(name)
                await expect(browser_page.locator('#batteries-grid .address')).to_have_text(address)
                await expect(browser_page.locator('#batteries-grid img, #batteries-grid script, #batteries-grid svg')).to_have_count(0)
                assert await browser_page.evaluate('window.injected === undefined')
                await expect(browser_page.locator('#batteries-grid .metrics')).to_have_count(int(has_telemetry))

    asyncio.run(scenario())


def test_dashboard_stream_failure_and_recovery() -> None:
    async def scenario() -> None:
        async with _browser_page() as page:
            with TestClient(build_app(_make_config(), StubTelemetryRepository(), start_poller=False)) as client:
                await page.route('http://monbat.test/**', lambda route: route.fulfill(
                    status=200, body=client.get('/').text, content_type='text/html'))
                await page.add_init_script("""
                  window.EventSource = class {
                    constructor(url) { window.stream = this; window.streamUrl = url; }
                  };
                """)
                await page.goto('http://monbat.test/')
                snapshot = {'latest': client.get('/api/latest').json(), 'summary': client.get('/api/summary').json()}
                await page.evaluate('(snapshot) => stream.onmessage({data: JSON.stringify(snapshot)})', snapshot)
                await expect(page.locator('#connection-status')).to_contain_text('Updated')
                before = await page.locator('#batteries-grid').inner_html()
                await page.evaluate('stream.onerror()')
                await expect(page.locator('#connection-status')).to_have_text('Connection paused')
                assert await page.locator('#batteries-grid').inner_html() == before
                await page.evaluate('(snapshot) => stream.onmessage({data: JSON.stringify(snapshot)})', snapshot)
                await expect(page.locator('#connection-status')).to_contain_text('Updated')
                assert await page.evaluate('streamUrl') == '/api/events'
    asyncio.run(scenario())


def test_dashboard_preserves_sparse_cell_slots() -> None:
    async def scenario() -> None:
        from monbat.bms import parse_bms_payload

        frame = captured_status_frame()
        frame[16:48] = bytes(32)
        struct.pack_into('<H', frame, 16, 3300)
        struct.pack_into('<H', frame, 20, 3350)
        telemetry = parse_bms_payload(checksum_correct_status_frame(frame), timestamp=1000)
        repo = StubTelemetryRepository(latest={'bat-1': telemetry})
        with TestClient(build_app(_make_config(), repo, start_poller=False)) as client:
            async with _browser_page() as page:
                await page.route('http://monbat.test/**', lambda route: route.fulfill(
                    status=200, body=client.get('/').text, content_type='text/html'))
                await page.add_init_script('window.EventSource = class { constructor() { window.stream = this; } };')
                await page.goto('http://monbat.test/')
                snapshot = {'latest': client.get('/api/latest').json(), 'summary': client.get('/api/summary').json()}
                await page.evaluate('(s) => stream.onmessage({data: JSON.stringify(s)})', snapshot)
                card = page.locator('#batteries-grid .card').first
                await expect(card.locator('.cells .chip')).to_have_text(['C1: 3.300 V', 'C3: 3.350 V'])
                await expect(card.locator('.cells-header')).to_have_text('Cell voltages (2)Δ 50.0 mV')
    asyncio.run(scenario())


@pytest.mark.parametrize('problem_flags,state', [(0x8000000000000000, 4), (0x8000000180000004, 99), (0, 4)])
def test_dashboard_preserves_state_and_named_protections(problem_flags: int, state: int) -> None:
    async def scenario() -> None:
        from monbat.bms import parse_bms_payload

        frame = captured_status_frame()
        struct.pack_into('<5h', frame, 52, 24, 0, 0, -12, -3)
        struct.pack_into('<Q', frame, 76, problem_flags)
        struct.pack_into('<I', frame, 84, 0x80008005)
        struct.pack_into('<H', frame, 88, state)
        telemetry = parse_bms_payload(checksum_correct_status_frame(frame), timestamp=1000)
        repo = StubTelemetryRepository(latest={'bat-1': telemetry})
        with TestClient(build_app(_make_config(), repo, start_poller=False)) as client:
            async with _browser_page() as page:
                await page.route('http://monbat.test/**', lambda route: route.fulfill(
                    status=200, body=client.get('/').text, content_type='text/html'))
                await page.add_init_script('window.EventSource = class { constructor() { window.stream = this; } };')
                await page.goto('http://monbat.test/')
                snapshot = {'latest': client.get('/api/latest').json(), 'summary': client.get('/api/summary').json()}
                await page.evaluate('(s) => stream.onmessage({data: JSON.stringify(s)})', snapshot)
                card = page.locator('#batteries-grid .card').first
                await expect(card).to_contain_text('BMS state: Disabled' if state == 4 else 'BMS state: Unknown (99)')
                if state == 99:
                    await expect(card.locator('.protections')).to_contain_text('Overcharge')
                else:
                    await expect(card).to_contain_text('No named low-word BMS protections reported')
                await expect(card.locator('img, script, svg')).to_have_count(0)
                assert REAL_STATUS.hex() not in await card.inner_text()
                snapshot['latest']['bat-1']['telemetry']['active_protections'] = ['<img src=x onerror="window.injected=true">']
                await page.evaluate('(s) => stream.onmessage({data: JSON.stringify(s)})', snapshot)
                await expect(card.locator('.protections')).to_contain_text('<img src=x onerror="window.injected=true">')
                await expect(card.locator('img')).to_have_count(0)
    asyncio.run(scenario())
