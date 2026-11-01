"""Async repository for local SQLite telemetry storage."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing

from monbat.bms import BatteryTelemetry, BmsState, CellReading, SocSource

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    battery_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    voltage_v REAL NOT NULL,
    current_a REAL NOT NULL,
    power_w REAL NOT NULL,
    soc_percent REAL NOT NULL,
    remaining_ah REAL NOT NULL,
    capacity_ah REAL NOT NULL,
    cell_temp_c INTEGER NOT NULL,
    bms_temp_c INTEGER NOT NULL,
    cell_readings_json TEXT NOT NULL,
    temperature_slots_json TEXT NOT NULL,
    balancing_mask INTEGER NOT NULL,
    problem_flags_hex TEXT NOT NULL,
    raw_response BLOB NOT NULL,
    reported_soc_percent REAL,
    soc_source TEXT NOT NULL,
    soh_percent REAL,
    cycle_count INTEGER NOT NULL,
    bms_state_raw INTEGER NOT NULL,
    bms_state TEXT NOT NULL,
    protection_flags INTEGER NOT NULL,
    active_protections_json TEXT NOT NULL
)
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_telemetry_battery_time
ON telemetry (battery_id, timestamp DESC)
"""

_BUSY_TIMEOUT_MS = 5_000


class TelemetryRepository:
    """Persist and query immutable battery telemetry snapshots."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def init_db(self) -> None:
        """Create the telemetry table and index, and enable WAL mode."""
        await asyncio.to_thread(self._init_db_sync)

    async def save_telemetry(
        self, battery_id: str, telemetry: BatteryTelemetry
    ) -> None:
        """Persist a telemetry snapshot without changing its values."""
        await asyncio.to_thread(self._save_telemetry_sync, battery_id, telemetry)

    async def get_latest_telemetry(
        self, battery_id: str
    ) -> BatteryTelemetry | None:
        """Return the newest snapshot for a battery, if one exists."""
        return await asyncio.to_thread(self._get_latest_telemetry_sync, battery_id)

    async def get_history(
        self, battery_id: str, since_timestamp: float
    ) -> list[BatteryTelemetry]:
        """Return snapshots since the given timestamp in chronological order."""
        return await asyncio.to_thread(
            self._get_history_sync, battery_id, since_timestamp
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        return connection

    def _init_db_sync(self) -> None:
        with closing(self._connect()) as connection:
            existing = connection.execute("PRAGMA table_info(telemetry)").fetchall()
            if existing:
                expected = {line.strip().split()[0] for line in _CREATE_TABLE_SQL.splitlines()[2:-1]}
                if {row["name"] for row in existing} != expected:
                    raise ValueError("Incompatible telemetry schema; select a new database path (sqlite_path)")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(_CREATE_TABLE_SQL)
            connection.execute(_CREATE_INDEX_SQL)
            connection.commit()

    def _save_telemetry_sync(
        self, battery_id: str, telemetry: BatteryTelemetry
    ) -> None:
        cell_readings_json = json.dumps([
            {"slot": cell.slot, "voltage_v": cell.voltage_v}
            for cell in telemetry.cell_readings
        ])
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO telemetry (
                    battery_id,
                    timestamp,
                    voltage_v,
                    current_a,
                    power_w,
                    soc_percent,
                    remaining_ah,
                    capacity_ah,
                    cell_temp_c,
                    bms_temp_c,
                    cell_readings_json, temperature_slots_json, balancing_mask,
                    problem_flags_hex, raw_response, reported_soc_percent, soc_source,
                    soh_percent, cycle_count, bms_state_raw, bms_state,
                    protection_flags, active_protections_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    battery_id,
                    telemetry.timestamp,
                    telemetry.voltage_v,
                    telemetry.current_a,
                    telemetry.power_w,
                    telemetry.soc_percent,
                    telemetry.remaining_ah,
                    telemetry.capacity_ah,
                    telemetry.cell_temp_c,
                    telemetry.bms_temp_c,
                    cell_readings_json,
                    json.dumps(telemetry.temperature_slots_c),
                    telemetry.balancing_mask,
                    f"{telemetry.problem_flags:016x}",
                    telemetry.raw_response,
                    telemetry.reported_soc_percent,
                    telemetry.soc_source,
                    telemetry.soh_percent,
                    telemetry.cycle_count,
                    telemetry.bms_state_raw,
                    telemetry.bms_state,
                    telemetry.protection_flags,
                    json.dumps(telemetry.active_protections),
                ),
            )
            connection.commit()

    def _get_latest_telemetry_sync(
        self, battery_id: str
    ) -> BatteryTelemetry | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT timestamp, voltage_v, current_a, power_w, soc_percent,
                       remaining_ah, capacity_ah, cell_temp_c, bms_temp_c,
                       cell_readings_json, temperature_slots_json, balancing_mask,
                       problem_flags_hex, raw_response, reported_soc_percent, soc_source,
                       soh_percent, cycle_count, bms_state_raw, bms_state,
                       protection_flags, active_protections_json
                FROM telemetry
                WHERE battery_id = ?
                ORDER BY timestamp DESC, id DESC
                LIMIT 1
                """,
                (battery_id,),
            ).fetchone()

        if row is None:
            return None
        return _telemetry_from_row(row)

    def _get_history_sync(
        self, battery_id: str, since_timestamp: float
    ) -> list[BatteryTelemetry]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT timestamp, voltage_v, current_a, power_w, soc_percent,
                       remaining_ah, capacity_ah, cell_temp_c, bms_temp_c,
                       cell_readings_json, temperature_slots_json, balancing_mask,
                       problem_flags_hex, raw_response, reported_soc_percent, soc_source,
                       soh_percent, cycle_count, bms_state_raw, bms_state,
                       protection_flags, active_protections_json
                FROM telemetry
                WHERE battery_id = ? AND timestamp >= ?
                ORDER BY timestamp ASC, id ASC
                """,
                (battery_id, since_timestamp),
            ).fetchall()

        return [_telemetry_from_row(row) for row in rows]


def _telemetry_from_row(row: sqlite3.Row) -> BatteryTelemetry:
    return BatteryTelemetry(
        timestamp=_as_float(row["timestamp"], "timestamp"),
        voltage_v=_as_float(row["voltage_v"], "voltage_v"),
        current_a=_as_float(row["current_a"], "current_a"),
        power_w=_as_float(row["power_w"], "power_w"),
        soc_percent=_as_float(row["soc_percent"], "soc_percent"),
        remaining_ah=_as_float(row["remaining_ah"], "remaining_ah"),
        capacity_ah=_as_float(row["capacity_ah"], "capacity_ah"),
        cell_temp_c=_as_int(row["cell_temp_c"], "cell_temp_c"),
        bms_temp_c=_as_int(row["bms_temp_c"], "bms_temp_c"),
        cell_readings=_decode_cell_readings(row["cell_readings_json"]),
        temperature_slots_c=_decode_temperature_slots(row["temperature_slots_json"]),
        balancing_mask=_as_int(row["balancing_mask"], "balancing_mask"),
        problem_flags=int(row["problem_flags_hex"], 16),
        raw_response=bytes(row["raw_response"]),
        reported_soc_percent=_optional_float(row["reported_soc_percent"], "reported_soc_percent"),
        soc_source=_soc_source(row["soc_source"]),
        soh_percent=_optional_float(row["soh_percent"], "soh_percent"),
        cycle_count=_as_int(row["cycle_count"], "cycle_count"),
        bms_state_raw=_as_int(row["bms_state_raw"], "bms_state_raw"),
        bms_state=_bms_state(row["bms_state"]),
        protection_flags=_as_int(row["protection_flags"], "protection_flags"),
        active_protections=_decode_protections(row["active_protections_json"]),
    )


def _as_float(value: object, column: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Invalid {column} value in telemetry database")
    return float(value)


def _as_int(value: object, column: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Invalid {column} value in telemetry database")
    return value


def _decode_cell_readings(value: object) -> tuple[CellReading, ...]:
    if not isinstance(value, str):
        raise ValueError("Invalid cell_readings_json value in telemetry database")
    decoded: object = json.loads(value)
    if not isinstance(decoded, list):
        raise ValueError("Cell readings must be stored as a JSON array")
    cells: list[CellReading] = []
    for cell in decoded:
        if not isinstance(cell, dict):
            raise ValueError("Cell readings must contain slot/voltage objects")
        slot = _as_int(cell.get("slot"), "cell slot")
        voltage = _as_float(cell.get("voltage_v"), "cell voltage")
        if not 1 <= slot <= 16 or (cells and slot <= cells[-1].slot) or voltage <= 0:
            raise ValueError("Invalid cell slot ordering or voltage")
        cells.append(CellReading(slot, voltage))
    return tuple(cells)


def _decode_temperature_slots(value: object) -> tuple[int, int, int, int, int]:
    if not isinstance(value, str):
        raise ValueError("Invalid temperature_slots_json value in telemetry database")
    decoded: object = json.loads(value)
    if not isinstance(decoded, list) or len(decoded) != 5:
        raise ValueError("Temperatures must contain five slots")
    slots = [_as_int(item, "temperature slot") for item in decoded]
    if any(not -32768 <= item <= 32767 for item in slots):
        raise ValueError("Temperature slot outside signed i16 range")
    return slots[0], slots[1], slots[2], slots[3], slots[4]


def _optional_float(value: object, column: str) -> float | None:
    return None if value is None else _as_float(value, column)


def _soc_source(value: object) -> SocSource:
    if value == "bms":
        return "bms"
    if value == "capacity":
        return "capacity"
    raise ValueError("Invalid soc_source in telemetry database")


def _bms_state(value: object) -> BmsState:
    match value:
        case "idle":
            return "idle"
        case "charging":
            return "charging"
        case "discharging":
            return "discharging"
        case "disabled":
            return "disabled"
        case "unknown":
            return "unknown"
        case _:
            raise ValueError("Invalid bms_state in telemetry database")


def _decode_protections(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise ValueError("Invalid active_protections_json in telemetry database")
    decoded: object = json.loads(value)
    if not isinstance(decoded, list):
        raise ValueError("Protections must be stored as a JSON array")
    protections: list[str] = []
    for label in decoded:
        if not isinstance(label, str):
            raise ValueError("Protection labels must be strings")
        protections.append(label)
    return tuple(protections)
