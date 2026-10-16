"""Async repository for local SQLite telemetry storage."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing

from monbat.bms import BatteryTelemetry

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
    cell_voltages_json TEXT NOT NULL
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
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(_CREATE_TABLE_SQL)
            connection.execute(_CREATE_INDEX_SQL)
            connection.commit()

    def _save_telemetry_sync(
        self, battery_id: str, telemetry: BatteryTelemetry
    ) -> None:
        cell_voltages_json = json.dumps(list(telemetry.cell_voltages_v))
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
                    cell_voltages_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    cell_voltages_json,
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
                       cell_voltages_json
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
                       cell_voltages_json
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
        cell_voltages_v=_decode_cell_voltages(row["cell_voltages_json"]),
    )


def _as_float(value: object, column: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Invalid {column} value in telemetry database")
    return float(value)


def _as_int(value: object, column: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Invalid {column} value in telemetry database")
    return value


def _decode_cell_voltages(value: object) -> tuple[float, ...]:
    if not isinstance(value, str):
        raise ValueError("Invalid cell_voltages_json value in telemetry database")

    decoded: object = json.loads(value)
    if not isinstance(decoded, list):
        raise ValueError("Cell voltages must be stored as a JSON array")

    cell_voltages: list[float] = []
    for voltage in decoded:
        if isinstance(voltage, bool) or not isinstance(voltage, (int, float)):
            raise ValueError("Cell voltages must contain only numeric values")
        cell_voltages.append(float(voltage))

    return tuple(cell_voltages)
