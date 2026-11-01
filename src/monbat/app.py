"""FastAPI service, Poller, and offline Dashboard for monbat."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import tomllib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse

from monbat.bms import BatteryTelemetry
from monbat.db import TelemetryRepository
from monbat.poller import Poller

logger = logging.getLogger(__name__)

BatteryStatus = Literal[
    "no-reading-yet", "offline", "charging", "discharging", "idle"
]


@dataclass(frozen=True, slots=True)
class PollerConfig:
    poll_interval_seconds: float
    timeout_seconds: float
    sqlite_path: str
    freshness_seconds: float = 60.0
    active_interval_seconds: float = 10.0
    concurrency: int = 1
    persistent_connections: bool = True


@dataclass(frozen=True, slots=True)
class ServerConfig:
    host: str
    port: int


@dataclass(frozen=True, slots=True)
class BatteryConfig:
    id: str
    name: str
    address: str


@dataclass(frozen=True, slots=True)
class AppConfig:
    poller: PollerConfig
    server: ServerConfig
    batteries: tuple[BatteryConfig, ...]


@dataclass(frozen=True, slots=True)
class BatteryLatestView:
    name: str
    address: str
    telemetry: BatteryTelemetry | None
    status: BatteryStatus
    cell_delta_mv: float | None


SummaryReason = Literal["missing-reading", "stale-reading", "invalid-capacity"]


@dataclass(frozen=True, slots=True)
class BatteryBankSummary:
    available: bool
    soc_percent: float | None
    power_w: float | None
    reason: SummaryReason | None


def _bank_summary(
    readings: list[BatteryTelemetry | None], freshness_seconds: float, now: float,
) -> BatteryBankSummary:
    if not readings or any(reading is None for reading in readings):
        return BatteryBankSummary(False, None, None, "missing-reading")
    telemetry = [reading for reading in readings if reading is not None]
    if any(now - reading.timestamp > freshness_seconds for reading in telemetry):
        return BatteryBankSummary(False, None, None, "stale-reading")
    if any(reading.capacity_ah <= 0 for reading in telemetry):
        return BatteryBankSummary(False, None, None, "invalid-capacity")
    capacity = sum(reading.capacity_ah for reading in telemetry)
    return BatteryBankSummary(
        True,
        sum(reading.soc_percent * reading.capacity_ah for reading in telemetry) / capacity,
        sum(reading.power_w for reading in telemetry),
        None,
    )


def _require_table(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"Configuration field {path!r} must be a table")

    table: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"Configuration field {path!r} has a non-string key")
        table[key] = item
    return table


def _require_value(table: dict[str, object], key: str, path: str) -> object:
    if key not in table:
        raise ValueError(f"Missing configuration field {path}.{key}")
    return table[key]


def _require_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Configuration field {path!r} must be a non-empty string")
    return value.strip()


def _require_positive_float(value: object, path: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"Configuration field {path!r} must be a positive number")
    return float(value)


def _require_port(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65_535:
        raise ValueError("Configuration field 'server.port' must be from 1 to 65535")
    return value


def _parse_config(value: object) -> AppConfig:
    root = _require_table(value, "root")
    poller_table = _require_table(_require_value(root, "poller", "root"), "poller")
    server_table = _require_table(_require_value(root, "server", "root"), "server")

    concurrency = poller_table.get("concurrency", 1)
    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or concurrency < 1:
        raise ValueError("poller.concurrency must be a positive integer")
    persistent = poller_table.get("persistent_connections", True)
    if not isinstance(persistent, bool):
        raise ValueError("poller.persistent_connections must be a boolean")
    poller = PollerConfig(
        concurrency=concurrency,
        persistent_connections=persistent,
        active_interval_seconds=_require_positive_float(
            poller_table.get("active_interval_seconds", 10), "poller.active_interval_seconds"
        ),
        poll_interval_seconds=_require_positive_float(
            _require_value(poller_table, "poll_interval_seconds", "poller"),
            "poller.poll_interval_seconds",
        ),
        timeout_seconds=_require_positive_float(
            _require_value(poller_table, "timeout_seconds", "poller"),
            "poller.timeout_seconds",
        ),
        freshness_seconds=_require_positive_float(
            poller_table.get("freshness_seconds", 60.0), "poller.freshness_seconds"
        ),
        sqlite_path=_require_string(
            _require_value(poller_table, "sqlite_path", "poller"),
            "poller.sqlite_path",
        ),
    )
    server = ServerConfig(
        host=_require_string(
            _require_value(server_table, "host", "server"), "server.host"
        ),
        port=_require_port(_require_value(server_table, "port", "server")),
    )

    raw_batteries = _require_value(root, "batteries", "root")
    if not isinstance(raw_batteries, list) or not raw_batteries:
        raise ValueError("Configuration field 'batteries' must be a non-empty array")

    batteries: list[BatteryConfig] = []
    battery_ids: set[str] = set()
    for index, raw_battery in enumerate(raw_batteries):
        battery_path = f"batteries[{index}]"
        battery_table = _require_table(raw_battery, battery_path)
        battery_id = _require_string(
            _require_value(battery_table, "id", battery_path), f"{battery_path}.id"
        )
        if battery_id in battery_ids:
            raise ValueError(f"Duplicate battery id {battery_id!r}")
        battery_ids.add(battery_id)

        name = _require_string(
            _require_value(battery_table, "name", battery_path),
            f"{battery_path}.name",
        )
        address_value = battery_table.get("address")
        if address_value is None:
            address_value = battery_table.get("mac_address")
        address = _require_string(address_value, f"{battery_path}.address")
        batteries.append(BatteryConfig(id=battery_id, name=name, address=address))

    return AppConfig(
        poller=poller,
        server=server,
        batteries=tuple(batteries),
    )


def _load_config(path: str = "config.toml") -> AppConfig:
    """Read and validate application settings from TOML."""
    try:
        with Path(path).open("rb") as config_file:
            raw_config: object = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Could not load configuration {path!r}: {exc}") from exc
    return _parse_config(raw_config)


def _status_for(
    telemetry: BatteryTelemetry | None,
    freshness_seconds: float,
    now: float,
) -> BatteryStatus:
    if telemetry is None:
        return "no-reading-yet"
    if now - telemetry.timestamp > freshness_seconds:
        return "offline"
    if telemetry.current_a > 0:
        return "charging"
    if telemetry.current_a < 0:
        return "discharging"
    return "idle"


def _cell_delta_mv(telemetry: BatteryTelemetry | None) -> float | None:
    if telemetry is None or not telemetry.cell_voltages_v:
        return None
    return round(
        (max(telemetry.cell_voltages_v) - min(telemetry.cell_voltages_v)) * 1000,
        1,
    )


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>monbat · Battery Dashboard</title>
  <style>
    :root { color-scheme: dark; --bg:#121418; --card:#1c2026; --border:#303741; --text:#e6edf3; --muted:#9aa4af; --green:#3fb950; --amber:#d29922; --red:#f85149; }
    * { box-sizing:border-box; }
    body { margin:0 auto; padding:1.5rem; max-width:1200px; background:var(--bg); color:var(--text); font:16px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }
    header { display:flex; justify-content:space-between; gap:1rem; align-items:baseline; border-bottom:1px solid var(--border); margin-bottom:1.5rem; padding-bottom:1rem; }
    h1 { margin:0; font-size:1.5rem; }
    #connection-status { color:var(--muted); font-size:.9rem; }
    .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr)); gap:1rem; }
    .card { display:flex; flex-direction:column; gap:1rem; padding:1.2rem; background:var(--card); border:1px solid var(--border); border-radius:10px; }
    .card-header,.soc-row,.cells-header { display:flex; justify-content:space-between; align-items:center; gap:.75rem; }
    .card-title { font-size:1.15rem; font-weight:650; }
    .address { color:var(--muted); font: .8rem ui-monospace,monospace; overflow-wrap:anywhere; }
    .badge { padding:.2rem .55rem; border:1px solid var(--border); border-radius:99px; color:var(--muted); font-size:.75rem; white-space:nowrap; }
    .badge.charging { color:var(--green); border-color:var(--green); }
    .badge.discharging { color:var(--amber); border-color:var(--amber); }
    .badge.offline { color:var(--red); border-color:var(--red); }
    .soc-row { font-weight:650; }
    .progress { height:12px; margin-top:.4rem; overflow:hidden; background:#303741; border-radius:8px; }
    .progress-fill { height:100%; background:var(--green); transition:width .25s ease; }
    .metrics { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.8rem; padding:.8rem; background:#15181c; border-radius:7px; }
    .metric-label { display:block; color:var(--muted); font-size:.72rem; text-transform:uppercase; }
    .metric-value { font-size:1.05rem; font-weight:600; font-variant-numeric:tabular-nums; }
    .charge { color:var(--green); }
    .discharge { color:var(--amber); }
    .cells { padding:.8rem; background:#15181c; border-radius:7px; }
    .cells-header { margin-bottom:.55rem; color:var(--muted); font-size:.8rem; }
    .chips { display:flex; flex-wrap:wrap; gap:.45rem; }
    .chip { padding:.2rem .4rem; background:#252b33; border-radius:4px; font: .8rem ui-monospace,monospace; }
    .empty { color:var(--muted); }
    .protections { color:var(--red); border:1px solid var(--red); padding:.8rem; border-radius:7px; }
    .bms-state { color:var(--muted); font-size:.85rem; }
    @media (max-width:520px) { body { padding:1rem; } header { align-items:flex-start; flex-direction:column; } }
  </style>
</head>
<body>
  <header>
    <h1>monbat</h1>
    <div id="connection-status" role="status">Loading battery readings…</div>
  </header>
  <section class="card" id="bank-summary" aria-label="Parallel Battery Bank" aria-live="polite" style="margin-bottom:1rem">
    <div class="card-title">Battery Bank · Parallel</div>
    <div class="empty">Fresh readings from all Batteries are required.</div>
  </section>
  <main class="grid" id="batteries-grid" aria-live="polite"></main>
  <script>
    const bankSummary = document.getElementById('bank-summary');
    const grid = document.getElementById('batteries-grid');
    const connectionStatus = document.getElementById('connection-status');
    const statusLabels = {
      'no-reading-yet': 'No reading yet',
      offline: 'Offline',
      charging: 'Charging',
      discharging: 'Discharging',
      idle: 'Idle'
    };

    function escapeText(value) {
      const text = document.createElement('span');
      text.textContent = String(value);
      return text.innerHTML;
    }

    function formatLocalTimestamp(date) {
      const pad = value => String(value).padStart(2, '0');
      const year = String(date.getFullYear()).padStart(4, '0');
      const month = pad(date.getMonth() + 1);
      const day = pad(date.getDate());
      const hours = pad(date.getHours());
      const minutes = pad(date.getMinutes());
      const seconds = pad(date.getSeconds());
      return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
    }

    function renderBattery(view) {
      const label = statusLabels[view.status] || view.status;
      const header = `
        <div class="card-header">
          <div><div class="card-title">${escapeText(view.name)}</div><div class="address">${escapeText(view.address)}</div></div>
          <span class="badge ${view.status}">${label}</span>
        </div>`;
      if (view.telemetry === null) {
        return `<article class="card">${header}</article>`;
      }

      const telemetry = view.telemetry;
      const bmsLabel = telemetry.bms_state === 'unknown'
        ? `Unknown (${telemetry.bms_state_raw})`
        : telemetry.bms_state.charAt(0).toUpperCase() + telemetry.bms_state.slice(1);
      const protections = telemetry.active_protections.length
        ? `<section class="protections" role="status"><strong>Active BMS protections</strong><ul>${telemetry.active_protections.map(label => `<li>${escapeText(label)}</li>`).join('')}</ul></section>`
        : '<div class="bms-state">No active BMS protections reported</div>';
      const soh = telemetry.soh_percent === null ? '—' : `${telemetry.soh_percent.toFixed(0)}%`;
      const currentClass = telemetry.current_a > 0 ? 'charge' : (telemetry.current_a < 0 ? 'discharge' : '');
      const currentSign = telemetry.current_a > 0 ? '+' : '';
      const powerSign = telemetry.power_w > 0 ? '+' : '';
      const stateOfCharge = Math.min(100, Math.max(0, telemetry.soc_percent));
      const cells = telemetry.cell_voltages_v.map((voltage, index) =>
        `<span class="chip">C${index + 1}: ${voltage.toFixed(3)} V</span>`
      ).join('');
      const delta = view.cell_delta_mv === null ? '—' : view.cell_delta_mv.toFixed(1);
      const lastUpdated = new Date(telemetry.timestamp * 1000);

      return `
        <article class="card">
          ${header}
          <time class="bms-state" datetime="${lastUpdated.toISOString()}">Last updated: ${formatLocalTimestamp(lastUpdated)}</time>
          <div class="bms-state">BMS state: ${escapeText(bmsLabel)}</div>
          ${protections}
          <section>
            <div class="soc-row"><span>State of charge</span><span>${telemetry.soc_percent.toFixed(1)}%</span></div>
            <div class="progress"><div class="progress-fill" style="width:${stateOfCharge}%"></div></div>
          </section>
          <section class="metrics" aria-label="Battery telemetry">
            <div><span class="metric-label">Voltage</span><span class="metric-value">${telemetry.voltage_v.toFixed(2)} V</span></div>
            <div><span class="metric-label">Current</span><span class="metric-value ${currentClass}">${currentSign}${telemetry.current_a.toFixed(2)} A</span></div>
            <div><span class="metric-label">Power</span><span class="metric-value ${currentClass}">${powerSign}${telemetry.power_w.toFixed(1)} W</span></div>
            <div><span class="metric-label">Capacity</span><span class="metric-value">${telemetry.remaining_ah.toFixed(1)} / ${telemetry.capacity_ah.toFixed(1)} Ah</span></div>
            <div><span class="metric-label">Cell temperature</span><span class="metric-value">${telemetry.cell_temp_c} °C</span></div>
            <div><span class="metric-label">BMS temperature</span><span class="metric-value">${telemetry.bms_temp_c} °C</span></div>
          </section>
          <div class="bms-state">SOH: ${soh} · Cycles: ${telemetry.cycle_count} · SOC source: ${telemetry.soc_source === 'bms' ? 'BMS' : 'Capacity estimate'}</div>
          <section class="cells">
            <div class="cells-header"><span>Cell voltages (${telemetry.cell_voltages_v.length})</span><span>Δ ${delta} mV</span></div>
            <div class="chips">${cells || '<span class="empty">No cell voltages</span>'}</div>
          </section>
        </article>`;
    }

    function renderDashboard(views) {
      grid.innerHTML = Object.values(views).map(renderBattery).join('');
    }

    function renderSummary(summary) {
      if (!summary.available) {
        const reason = summary.reason === 'invalid-capacity'
          ? 'Valid capacity from all Batteries is required.'
          : 'Fresh readings from all Batteries are required.';
        bankSummary.innerHTML = `<div class="card-title">Battery Bank · Parallel</div><div class="empty">${reason}</div>`;
        return;
      }
      const soc = summary.soc_percent;
      const power = summary.power_w;
      const state = power > 0 ? 'Charging' : power < 0 ? 'Discharging' : 'Idle';
      const powerClass = power > 0 ? 'charge' : power < 0 ? 'discharge' : '';
      bankSummary.innerHTML = `
        <div class="card-header"><div class="card-title">Battery Bank · Parallel</div>
          <span class="metric-value ${powerClass}">${state} · ${power > 0 ? '+' : ''}${power.toFixed(1)} W</span></div>
        <div><div class="soc-row"><span>State of charge</span><span>${soc.toFixed(1)}%</span></div>
          <div class="progress" role="progressbar" aria-label="Battery Bank state of charge" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${soc}">
            <div class="progress-fill" style="width:${Math.min(100, Math.max(0, soc))}%"></div>
          </div></div>`;
    }

    async function fetchJson(url, options) {
      const response = await fetch(url, options);
      if (!response.ok) throw new Error('Dashboard request failed');
      return response.json();
    }

    const events = new EventSource('/api/events');
    events.onmessage = event => {
      const snapshot = JSON.parse(event.data);
      renderDashboard(snapshot.latest);
      renderSummary(snapshot.summary);
      connectionStatus.textContent = `Updated ${new Date().toLocaleTimeString()}`;
    };
    events.onerror = () => {
      connectionStatus.textContent = 'Connection paused';
    };
  </script>
</body>
</html>
"""


def build_app(
    config: AppConfig,
    repo: TelemetryRepository,
    *,
    start_poller: bool = True,
) -> FastAPI:
    """Build the service around one shared configuration and repository."""

    poller: Poller | None = None

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        nonlocal poller
        await repo.init_db()
        poller_task: asyncio.Task[None] | None = None
        if start_poller:
            poller = Poller(config, repo)
            poller_task = asyncio.create_task(poller.run())
        try:
            yield
        finally:
            poller = None
            if poller_task is not None:
                poller_task.cancel()
                try:
                    await poller_task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(lifespan=lifespan)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> HTMLResponse:
        return HTMLResponse(_DASHBOARD_HTML)

    @app.post("/api/refresh")
    async def request_refresh() -> dict[str, str]:
        return {"outcome": poller.request_refresh() if poller is not None else "disabled"}

    @app.get("/api/latest")
    async def latest() -> dict[str, object]:
        now = time.time()
        result: dict[str, object] = {}
        for battery in config.batteries:
            telemetry = await repo.get_latest_telemetry(battery.id)
            view = BatteryLatestView(
                name=battery.name,
                address=battery.address,
                telemetry=telemetry,
                status=_status_for(
                    telemetry, config.poller.freshness_seconds, now
                ),
                cell_delta_mv=_cell_delta_mv(telemetry),
            )
            result[battery.id] = asdict(view)
        return result

    @app.get("/api/summary")
    async def summary() -> BatteryBankSummary:
        readings = [
            await repo.get_latest_telemetry(battery.id)
            for battery in config.batteries
        ]
        return _bank_summary(readings, config.poller.freshness_seconds, time.time())

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        async def stream() -> AsyncIterator[str]:
            subscriber = poller
            if subscriber is not None:
                subscriber.subscribe()
            try:
                previous = ""
                while True:
                    snapshot = json.dumps({
                        "latest": await latest(),
                        "summary": asdict(await summary()),
                    }, allow_nan=False)
                    if snapshot != previous:
                        logger.debug("[DEBUG-resume] SSE snapshot yielded bytes=%d", len(snapshot))
                        yield f"data: {snapshot}\n\n"
                        previous = snapshot
                    else:
                        yield ": heartbeat\n\n"
                    # Also detect freshness expiry when BLE yields no new data.
                    await asyncio.sleep(1)
            finally:
                if subscriber is not None:
                    subscriber.unsubscribe()
        return StreamingResponse(stream(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
        })

    @app.get("/api/history")
    async def history(
        hours: float = Query(default=24.0, gt=0.0),
    ) -> list[dict[str, object]]:
        since_timestamp = time.time() - hours * 3600
        rows: list[tuple[float, str, dict[str, object]]] = []
        for battery in config.batteries:
            telemetry_rows = await repo.get_history(battery.id, since_timestamp)
            for telemetry in telemetry_rows:
                row: dict[str, object] = {
                    "battery_id": battery.id,
                    "name": battery.name,
                    "address": battery.address,
                }
                row.update(asdict(telemetry))
                rows.append((telemetry.timestamp, battery.id, row))

        rows.sort(key=lambda row: (row[0], row[1]))
        return [row[2] for row in rows]

    return app


def serve(config_path: str = "config.toml", *, log_level: str = "info") -> None:
    """Load local configuration and run Uvicorn with the configured service."""
    if log_level not in {"debug", "info", "warning", "error", "critical"}:
        raise SystemExit("Log level must be debug, info, warning, error, or critical")
    try:
        config = _load_config(config_path)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    repo = TelemetryRepository(config.poller.sqlite_path)
    app = build_app(config, repo)

    import uvicorn

    from copy import deepcopy
    from uvicorn.config import LOGGING_CONFIG

    log_config = deepcopy(LOGGING_CONFIG)
    log_config["formatters"]["default"]["fmt"] = (
        "%(asctime)s %(levelprefix)s %(message)s"
    )
    log_config["formatters"]["default"]["datefmt"] = "%Y-%m-%d %H:%M:%S %z"
    log_config["formatters"]["access"]["fmt"] = (
        '%(asctime)s %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
    )
    log_config["formatters"]["access"]["datefmt"] = "%Y-%m-%d %H:%M:%S %z"
    log_config["loggers"]["monbat"] = {
        "handlers": ["default"], "level": log_level.upper(), "propagate": False,
    }
    uvicorn.run(
        app, host=config.server.host, port=config.server.port, log_config=log_config,
        log_level=log_level,
    )
