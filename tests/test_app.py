from __future__ import annotations

import asyncio
import json
import logging
import re
import struct
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace
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
    assert response.text.count("http://") == 1
    assert "http://www.w3.org/2000/svg" in response.text
    assert not re.search(r"(?:src|href)\s*=\s*['\"]https?://", response.text, re.I)


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
async def _browser_page(*, mobile: bool = False) -> AsyncGenerator[Page, None]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            if mobile:
                page = await browser.new_page(
                    viewport={'width': 390, 'height': 844},
                    is_mobile=True,
                    has_touch=True,
                )
            else:
                page = await browser.new_page()
            yield page
        finally:
            await browser.close()


async def _fulfill_test_app_request(route: Route, client: TestClient) -> None:
    response = client.request(route.request.method, route.request.url)
    await route.fulfill(
        status=response.status_code,
        body=response.content,
        content_type=response.headers.get('content-type', 'application/json'),
    )


async def _install_dashboard_app_bridge(
    page: Page,
    client: TestClient,
    history_requests: list[str],
    *,
    now_ms: int,
) -> None:
    await page.add_init_script(f"""
      window.testNowMs = {now_ms};
      Date.now = () => window.testNowMs;
      window.eventSourceCount = 0;
      window.dashboardEvents = null;
      window.EventSource = class {{
        constructor(url) {{
          window.eventSourceCount += 1;
          window.dashboardEvents = this;
          this.url = url;
        }}
      }};
    """)

    async def serve(route: Route) -> None:
        if '/api/history' in route.request.url:
            history_requests.append(route.request.url)
        await _fulfill_test_app_request(route, client)

    await page.route('http://monbat.test/**', serve)


def test_history_tab_loads_on_entry_stays_static_and_reloads_on_reentry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        now = [1_750_000_000.0]
        monkeypatch.setattr(app_module.time, 'time', lambda: now[0])
        telemetry = _make_telemetry(now[0] - 10)
        repo = StubTelemetryRepository(
            latest={'one': telemetry},
            history={'one': [_make_telemetry(now[0] - 60)]},
        )
        config = _make_config(
            batteries=(BatteryConfig('one', 'Cabin Battery', 'synthetic-address'),),
            poll_interval_seconds=47.0,
        )
        with TestClient(build_app(config, repo, start_poller=False)) as client:
            async with _browser_page() as page:
                history_requests: list[str] = []
                await _install_dashboard_app_bridge(
                    page, client, history_requests, now_ms=int(now[0] * 1000),
                )
                await page.goto('http://monbat.test/')

                dashboard_tab = page.get_by_role('tab', name='Dashboard')
                history_tab = page.get_by_role('tab', name='History')
                await expect(dashboard_tab).to_have_attribute('aria-selected', 'true')
                await expect(history_tab).to_have_attribute('aria-selected', 'false')
                assert history_requests == []
                assert await page.evaluate('window.eventSourceCount') == 1

                await dashboard_tab.focus()
                await page.keyboard.press('ArrowRight')
                await expect(history_tab).to_have_attribute('aria-selected', 'true')
                await expect(page.locator('#history-window')).to_be_visible()
                assert len(history_requests) == 1
                assert history_requests[0].endswith('/api/history?hours=24')
                first_window = await page.locator('#history-window').inner_text()

                now[0] += 3600
                await page.evaluate('(now) => window.testNowMs = now * 1000', now[0])
                repo.latest['one'] = replace(telemetry, soc_percent=73.0)
                snapshot = {
                    'latest': client.get('/api/latest').json(),
                    'summary': client.get('/api/summary').json(),
                }
                await page.evaluate(
                    '(value) => dashboardEvents.onmessage({data: JSON.stringify(value)})',
                    snapshot,
                )
                await expect(page.locator('#batteries-grid')).to_contain_text('73.0%')
                await expect(page.locator('#history-window')).to_have_text(first_window)
                assert len(history_requests) == 1
                assert await page.evaluate('window.eventSourceCount') == 1

                await history_tab.click()
                assert len(history_requests) == 1
                await dashboard_tab.click()
                await history_tab.click()
                await expect(page.locator('#history-window')).not_to_have_text(first_window)
                assert len(history_requests) == 2
                assert await page.evaluate('window.eventSourceCount') == 1

    asyncio.run(scenario())


def test_history_chart_connects_stored_soc_across_polling_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        now = 1_750_000_000.0
        monkeypatch.setattr(app_module.time, 'time', lambda: now)
        name = '<img src=x onerror="window.injected=true"> & “Cabin”'
        first_time = now - 120
        history = [
            replace(_make_telemetry(first_time), soc_percent=0.0),
            replace(_make_telemetry(first_time + 19), soc_percent=100.0),
            replace(_make_telemetry(first_time + 39), soc_percent=37.5),
            replace(_make_telemetry(now - 1), soc_percent=62.5),
            replace(_make_telemetry(now - 24 * 3600 - 1), soc_percent=25.0),
            replace(_make_telemetry(now + 1), soc_percent=90.0),
        ]
        repo = StubTelemetryRepository(
            history={
                'one': history,
                'two': [replace(_make_telemetry(now - 30), soc_percent=100.0)],
            }
        )
        config = _make_config(
            batteries=(
                BatteryConfig('one', name, 'synthetic-one'),
                BatteryConfig('two', 'Second Battery', 'synthetic-two'),
                BatteryConfig('three', 'No history Battery', 'synthetic-three'),
            ),
            poll_interval_seconds=20.0,
        )
        with TestClient(build_app(config, repo, start_poller=False)) as client:
            async with _browser_page() as page:
                await page.set_viewport_size({'width': 1280, 'height': 800})
                history_requests: list[str] = []
                await _install_dashboard_app_bridge(
                    page, client, history_requests, now_ms=int(now * 1000),
                )
                await page.goto('http://monbat.test/')
                await page.get_by_role('tab', name='History').click()
                await expect(page.locator('#history-chart')).to_be_visible()
                assert history_requests[0].endswith('/api/history?hours=24')

                await expect(page.get_by_text(name, exact=True)).to_be_visible()
                await expect(page.get_by_text('Second Battery', exact=True)).to_be_visible()
                await expect(page.get_by_text('No history Battery', exact=True)).to_be_visible()
                assert await page.evaluate('window.injected === undefined')
                assert await page.locator('#history-chart img, #history-chart script').count() == 0

                color_values = await page.locator('.history-legend-swatch').evaluate_all(
                    "items => items.map(item => getComputedStyle(item).backgroundColor)"
                )
                assert len(color_values) == 3
                assert len(set(color_values)) == 3

                await expect(page.get_by_role('button', name=re.compile(r', 0\.0% SOC$'))).to_have_count(1)
                await expect(page.get_by_role('button', name=re.compile(r', 100\.0% SOC$'))).to_have_count(2)
                await expect(page.get_by_role('button', name=re.compile(r', 37\.5% SOC$'))).to_have_count(1)
                await expect(page.get_by_role('button', name=re.compile(r', 62\.5% SOC$'))).to_have_count(1)
                assert await page.get_by_role('button', name=re.compile(r'% SOC')).count() == 5

                first_battery_segments = page.get_by_role(
                    'img', name=re.compile(r'4 connected readings')
                )
                await expect(first_battery_segments).to_have_count(1)
                assert await page.locator('.history-series polyline').count() == 1
                await expect(page.locator('.history-y-axis-label').first).to_have_text('100%')
                await expect(page.locator('.history-y-axis-label').last).to_have_text('0%')

    asyncio.run(scenario())


@pytest.mark.parametrize('mobile', [False, True])
def test_history_hourly_grid_and_dense_readings_stay_readable(mobile: bool) -> None:
    async def scenario() -> None:
        now = 1_750_000_000.0
        dense = [
            replace(_make_telemetry(now - 1200 + index * 10), soc_percent=60 - index * 0.05)
            for index in range(120)
        ]
        isolated = replace(_make_telemetry(now - 7200), soc_percent=40.0)
        repo = StubTelemetryRepository(history={
            'one': [isolated, *dense],
            'two': [replace(reading, soc_percent=reading.soc_percent - 1) for reading in dense],
            'three': [replace(isolated, soc_percent=25.0)],
        })
        config = _make_config(batteries=(
            BatteryConfig('one', 'First Battery', 'synthetic-one'),
            BatteryConfig('two', 'Second Battery', 'synthetic-two'),
            BatteryConfig('three', 'Third Battery', 'synthetic-three'),
        ))
        with TestClient(build_app(config, repo, start_poller=False)) as client:
            async with _browser_page(mobile=mobile) as page:
                await _install_dashboard_app_bridge(page, client, [], now_ms=int(now * 1000))
                await page.goto('http://monbat.test/')
                await page.get_by_role('tab', name='History').click()
                await expect(page.locator('.history-reading')).to_have_count(242)
                grid = await page.locator('.history-hour-grid-line').evaluate_all(
                    "lines => lines.map(line => Number(line.getAttribute('x1')))"
                )
                assert len(grid) == 24
                spacing = grid[1] - grid[0]
                assert all(abs((second - first) - spacing) < 0.001 for first, second in zip(grid, grid[1:]))
                # The first line is at the next whole local clock hour, rather
                # than one hour after the arbitrary window start.
                first_hour_offset = await page.evaluate("""() => {
                    const start = new Date(window.testNowMs - 86400000);
                    const hour = new Date(start);
                    hour.setMinutes(0, 0, 0);
                    if (hour < start) hour.setTime(hour.getTime() + 3600000);
                    return (hour - start) / 3600000;
                }""")
                assert abs(grid[0] - (56 + spacing * first_hour_offset)) < 0.001
                if not mobile:
                    label_positions = await page.locator('.history-x-axis-label').evaluate_all(
                        "labels => labels.map(label => Number(label.getAttribute('x')))"
                    )
                    assert label_positions == grid
                    expected_hours = await page.evaluate("""() => {
                        const hour = new Date(window.testNowMs - 86400000);
                        hour.setMinutes(0, 0, 0);
                        if (hour.getTime() < window.testNowMs - 86400000) hour.setTime(hour.getTime() + 3600000);
                        return Array.from({length: 24}, (_, index) => String(new Date(hour.getTime() + index * 3600000).getHours()).padStart(2, '0'));
                    }""")
                    assert await page.locator('.history-x-axis-label').all_text_contents() == expected_hours
                labels = await page.locator('.history-x-axis-label').evaluate_all(
                    "labels => labels.map(label => { const box = label.getBoundingClientRect(); return {left: box.left, right: box.right}; })"
                )
                assert all(first['right'] < second['left'] for first, second in zip(labels, labels[1:]))
                connected = page.get_by_role('button', name=re.compile(r'First Battery, .*54\.1% SOC$')).first
                await expect(connected.locator('.history-reading-dot')).to_be_hidden()
                await expect(page.get_by_role('img', name=re.compile(r'121 connected readings'))).to_have_count(1)
                await expect(page.get_by_role('img', name=re.compile(r'120 connected readings'))).to_have_count(1)
                isolated_point = page.get_by_role('button', name=re.compile(r', 25\.0% SOC$'))
                await expect(isolated_point.locator('.history-reading-dot')).to_be_visible()
                assert await isolated_point.locator('.history-reading-dot').evaluate(
                    "dot => Number(dot.getAttribute('r')) <= 2 && getComputedStyle(dot).stroke === 'none'"
                )
                await connected.focus()
                await expect(connected.locator('.history-reading-dot')).to_be_visible()
                await expect(page.locator('#history-tooltip')).to_have_text(
                    await connected.get_attribute('aria-label') or ''
                )
                await isolated_point.focus()
                await expect(connected.locator('.history-reading-dot')).to_be_hidden()
                await expect(page.locator('.history-reading-selected')).to_have_count(1)

    asyncio.run(scenario())


def test_history_loading_empty_failure_and_retry_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        now = [1_750_000_000.0]
        monkeypatch.setattr(app_module.time, 'time', lambda: now[0])
        repo = StubTelemetryRepository(
            history={'one': [replace(_make_telemetry(now[0] - 60), soc_percent=54.0)]},
        )
        config = _make_config(
            batteries=(BatteryConfig('one', 'Workshop Battery', 'synthetic-address'),),
        )
        with TestClient(build_app(config, repo, start_poller=False)) as client:
            async with _browser_page() as page:
                await page.add_init_script(f"""
                  window.testNowMs = {int(now[0] * 1000)};
                  Date.now = () => window.testNowMs;
                  window.EventSource = class {{ constructor() {{ window.eventSourceCount = (window.eventSourceCount || 0) + 1; }} }};
                """)
                history_requests: list[str] = []

                async def serve(route: Route) -> None:
                    if '/api/history' in route.request.url:
                        history_requests.append(route.request.url)
                        if len(history_requests) == 1:
                            await asyncio.sleep(0.2)
                        elif len(history_requests) == 2:
                            await route.fulfill(
                                status=503, body='{}', content_type='application/json',
                            )
                            return
                    await _fulfill_test_app_request(route, client)

                await page.route('http://monbat.test/**', serve)
                await page.goto('http://monbat.test/')
                history_tab = page.get_by_role('tab', name='History')
                await history_tab.click()
                await expect(page.locator('#history-state')).to_have_text('Loading SOC history…')
                await expect(page.get_by_role('button', name=re.compile(r', 54\.0% SOC$'))).to_be_visible()

                await page.get_by_role('tab', name='Dashboard').click()
                await history_tab.click()
                await expect(page.locator('#history-state')).to_contain_text('Unable to load SOC history')
                await expect(page.locator('#history-chart-content')).to_be_hidden()
                await expect(page.locator('#history-window')).to_be_hidden()
                assert await page.locator('#history-chart [role="button"]').count() == 0

                repo.history['one'] = []
                await page.get_by_role('tab', name='Dashboard').click()
                await history_tab.click()
                await expect(page.locator('#history-state')).to_have_text('No readings in the last 24 hours')
                assert len(history_requests) == 3

    asyncio.run(scenario())


@pytest.mark.parametrize('mobile', [False, True])
def test_history_reading_details_work_with_mouse_and_touch(mobile: bool) -> None:
    async def scenario() -> None:
        now = 1_750_000_000.0
        repo = StubTelemetryRepository(
            history={
                'one': [
                    replace(_make_telemetry(now - 7200), soc_percent=35.0),
                    replace(_make_telemetry(now - 600), soc_percent=65.0),
                ]
            }
        )
        config = _make_config(
            batteries=(BatteryConfig('one', 'Workshop Battery', 'synthetic-address'),),
            poll_interval_seconds=20_000.0,
        )
        with TestClient(build_app(config, repo, start_poller=False)) as client:
            async with _browser_page(mobile=mobile) as page:
                history_requests: list[str] = []
                await _install_dashboard_app_bridge(
                    page, client, history_requests, now_ms=int(now * 1000),
                )
                await page.goto('http://monbat.test/')
                await page.get_by_role('tab', name='History').click()
                reading = page.get_by_role('button', name=re.compile(r', 65\.0% SOC$'))
                detail = await reading.get_attribute('aria-label')
                assert detail is not None
                if mobile:
                    await reading.tap()
                else:
                    await reading.hover()
                await expect(page.locator('#history-tooltip')).to_have_text(detail)
                await expect(reading.locator('.history-reading-dot')).to_be_visible()
                assert 'Workshop Battery' in detail
                assert '65.0% SOC' in detail

    asyncio.run(scenario())


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
                    await _fulfill_test_app_request(route, client)

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


def test_service_shutdown_closes_open_sse_and_runs_cleanup(tmp_path: Path) -> None:
    import http.client
    import signal
    import socket
    import subprocess
    import time

    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    config = tmp_path / 'config.toml'
    config.write_text(f'''[poller]
poll_interval_seconds = 600
timeout_seconds = 10
sqlite_path = "{tmp_path / 'telemetry.db'}"
[server]
host = "127.0.0.1"
port = {port}
[[batteries]]
id = "one"
name = "Battery"
address = "synthetic-address"
''')
    cleanup = tmp_path / 'cleanup.txt'
    script = '''
import sys
from pathlib import Path
from contextlib import asynccontextmanager
import monbat.app as module
original_build = module.build_app

def build(config, repo):
    app = original_build(config, repo, start_poller=False)
    original_lifespan = app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(app):
        async with original_lifespan(app):
            yield
        Path(sys.argv[2]).write_text('finished')
    app.router.lifespan_context = lifespan
    return app

module.build_app = build
module.serve(sys.argv[1])
'''
    with (tmp_path / 'service.log').open('w') as log:
        process = subprocess.Popen([sys.executable, '-c', script, str(config), str(cleanup)], stdout=log, stderr=log)
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
        try:
            deadline = time.monotonic() + 10
            while True:
                try:
                    connection.request('GET', '/api/events')
                    response = connection.getresponse()
                    break
                except OSError:
                    connection.close()
                    assert process.poll() is None
                    if time.monotonic() >= deadline:
                        pytest.fail('Service did not start')
                    time.sleep(0.05)
            assert response.status == 200
            assert response.readline().startswith(b'data:')
            started = time.monotonic()
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                pytest.fail('Open SSE request prevented bounded shutdown')
            assert time.monotonic() - started < 8
            assert cleanup.read_text() == 'finished'
        finally:
            connection.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
