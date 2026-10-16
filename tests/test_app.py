from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import monbat
import monbat.app as app_module
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
    repo = StubTelemetryRepository()
    polled_addresses: list[str] = []
    telemetry = _make_telemetry(1_000.0)

    async def poll(address: str, timeout_seconds: float) -> BatteryTelemetry:
        polled_addresses.append(address)
        if address == config.batteries[0].address:
            raise TimeoutError("no response")
        return telemetry

    async def stop_after_pass(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(app_module, "poll_battery", poll)
    monkeypatch.setattr(app_module.asyncio, "sleep", stop_after_pass)

    with caplog.at_level(logging.WARNING, logger="monbat.app"):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(app_module.run_poller_task(config, repo))

    assert polled_addresses == [
        "AA:BB:CC:00:00:01",
        "AA:BB:CC:00:00:02",
    ]
    assert repo.saved == [("bat-2", telemetry)]
    assert "Poll failed for battery bat-1" in caplog.text


def test_dashboard_html_is_self_contained() -> None:
    app = build_app(_make_config(), StubTelemetryRepository(), start_poller=False)

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "setInterval(updateDashboard, 10000)" in response.text
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
