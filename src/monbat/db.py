"""Async repository for local SQLite telemetry storage."""

from __future__ import annotations

import asyncio
import json
import math
import sqlite3
from contextlib import closing

from monbat.bms import BatteryTelemetry, BmsState, CellReading, SocSource

_TELEMETRY_INDEX_NAME = "idx_telemetry_battery_time"

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

_CREATE_INDEX_SQL = f"""
CREATE INDEX IF NOT EXISTS {_TELEMETRY_INDEX_NAME}
ON telemetry (battery_id, timestamp DESC)
"""

# Keep this signature aligned with _CREATE_TABLE_SQL.
_EXPECTED_TELEMETRY_COLUMNS = (
    ("id", "INTEGER", 0, None, 1),
    ("battery_id", "TEXT", 1, None, 0),
    ("timestamp", "REAL", 1, None, 0),
    ("voltage_v", "REAL", 1, None, 0),
    ("current_a", "REAL", 1, None, 0),
    ("power_w", "REAL", 1, None, 0),
    ("soc_percent", "REAL", 1, None, 0),
    ("remaining_ah", "REAL", 1, None, 0),
    ("capacity_ah", "REAL", 1, None, 0),
    ("cell_temp_c", "INTEGER", 1, None, 0),
    ("bms_temp_c", "INTEGER", 1, None, 0),
    ("cell_readings_json", "TEXT", 1, None, 0),
    ("temperature_slots_json", "TEXT", 1, None, 0),
    ("balancing_mask", "INTEGER", 1, None, 0),
    ("problem_flags_hex", "TEXT", 1, None, 0),
    ("raw_response", "BLOB", 1, None, 0),
    ("reported_soc_percent", "REAL", 0, None, 0),
    ("soc_source", "TEXT", 1, None, 0),
    ("soh_percent", "REAL", 0, None, 0),
    ("cycle_count", "INTEGER", 1, None, 0),
    ("bms_state_raw", "INTEGER", 1, None, 0),
    ("bms_state", "TEXT", 1, None, 0),
    ("protection_flags", "INTEGER", 1, None, 0),
    ("active_protections_json", "TEXT", 1, None, 0),
)
_EXPECTED_TELEMETRY_INDEX_COLUMNS = (
    ("battery_id", 0, "BINARY"),
    ("timestamp", 1, "BINARY"),
)
_SCHEMA_ERROR = (
    "Incompatible telemetry schema; select a new database path (sqlite_path)"
)

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
            has_telemetry_schema = _check_existing_schema(connection)
            connection.execute("PRAGMA journal_mode = WAL")
            if not has_telemetry_schema:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(_CREATE_TABLE_SQL)
                    connection.execute(_CREATE_INDEX_SQL)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise

    def _save_telemetry_sync(
        self, battery_id: str, telemetry: BatteryTelemetry
    ) -> None:
        _validate_telemetry(telemetry)
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


def _check_existing_schema(connection: sqlite3.Connection) -> bool:
    table = connection.execute(
        "SELECT type, sql FROM sqlite_master WHERE name = 'telemetry'"
    ).fetchone()
    if table is None:
        index = connection.execute(
            "SELECT type FROM sqlite_master WHERE name = ?",
            (_TELEMETRY_INDEX_NAME,),
        ).fetchone()
        if index is not None:
            raise ValueError(_SCHEMA_ERROR)
        return False

    actual_columns = tuple(
        (
            row["name"],
            row["type"].upper(),
            row["notnull"],
            row["dflt_value"],
            row["pk"],
        )
        for row in connection.execute("PRAGMA table_info(telemetry)")
    )
    if (
        table["type"] != "table"
        or actual_columns != _EXPECTED_TELEMETRY_COLUMNS
        or table["sql"] is None
        or "AUTOINCREMENT" not in table["sql"].upper()
    ):
        raise ValueError(_SCHEMA_ERROR)

    index = next(
        (
            row
            for row in connection.execute("PRAGMA index_list(telemetry)")
            if row["name"] == _TELEMETRY_INDEX_NAME
        ),
        None,
    )
    index_columns = (
        tuple(
            (row["name"], row["desc"], row["coll"])
            for row in connection.execute(
                f"PRAGMA index_xinfo({_TELEMETRY_INDEX_NAME})"
            )
            if row["key"]
        )
        if index is not None
        else ()
    )
    if (
        index is None
        or index["unique"] != 0
        or index["origin"] != "c"
        or index["partial"] != 0
        or index_columns != _EXPECTED_TELEMETRY_INDEX_COLUMNS
    ):
        raise ValueError(_SCHEMA_ERROR)
    return True


def _telemetry_from_row(row: sqlite3.Row) -> BatteryTelemetry:
    telemetry = BatteryTelemetry(
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
        balancing_mask=_require_uint(row["balancing_mask"], 32, "balancing_mask"),
        problem_flags=_decode_problem_flags_hex(row["problem_flags_hex"]),
        raw_response=_validate_raw_response(row["raw_response"]),
        reported_soc_percent=_optional_float(row["reported_soc_percent"], "reported_soc_percent"),
        soc_source=_soc_source(row["soc_source"]),
        soh_percent=_optional_float(row["soh_percent"], "soh_percent"),
        cycle_count=_as_int(row["cycle_count"], "cycle_count"),
        bms_state_raw=_as_int(row["bms_state_raw"], "bms_state_raw"),
        bms_state=_bms_state(row["bms_state"]),
        protection_flags=_as_int(row["protection_flags"], "protection_flags"),
        active_protections=_decode_protections(row["active_protections_json"]),
    )
    _validate_telemetry(telemetry)
    return telemetry


def _as_float(value: object, column: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Invalid {column} value")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"Invalid {column} value") from exc
    if not math.isfinite(number):
        raise ValueError(f"Invalid {column} value")
    return number


def _require_uint(value: object, bits: int, column: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value < 1 << bits
    ):
        raise ValueError(f"Invalid {column}; expected an unsigned u{bits} value")
    return value


def _require_sint(value: object, bits: int, column: str) -> int:
    minimum = -(1 << (bits - 1))
    maximum = (1 << (bits - 1)) - 1
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"Invalid {column}; expected a signed i{bits} value")
    return value


def _require_float_range(
    value: object, minimum: float, maximum: float, column: str
) -> float:
    number = _as_float(value, column)
    if not minimum <= number <= maximum:
        raise ValueError(f"Invalid {column}; outside its supported range")
    return number


def _as_int(value: object, column: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Invalid {column} value")
    return value


def _validate_telemetry(telemetry: BatteryTelemetry) -> None:
    _as_float(telemetry.timestamp, "timestamp")
    voltage = _require_float_range(telemetry.voltage_v, 0, 65.535, "voltage_v")
    current = _require_float_range(
        telemetry.current_a, -2_147_483.648, 2_147_483.647, "current_a"
    )
    power = _as_float(telemetry.power_w, "power_w")
    if power != round(voltage * current, 2):
        raise ValueError("power_w must match voltage_v multiplied by current_a")
    _require_float_range(telemetry.soc_percent, 0, 100, "soc_percent")
    _require_float_range(telemetry.remaining_ah, 0, 655.35, "remaining_ah")
    _require_float_range(telemetry.capacity_ah, 0, 42_949_672.95, "capacity_ah")

    _require_uint(telemetry.balancing_mask, 32, "balancing_mask")
    problem_flags = _require_uint(telemetry.problem_flags, 64, "problem_flags")
    protection_flags = _require_uint(
        telemetry.protection_flags, 32, "protection_flags"
    )
    if protection_flags != problem_flags & 0xFFFFFFFF:
        raise ValueError("protection_flags must match the low 32 bits of problem_flags")

    _require_uint(telemetry.cycle_count, 32, "cycle_count")
    state_raw = _require_uint(telemetry.bms_state_raw, 16, "bms_state_raw")
    state = _bms_state(telemetry.bms_state)
    expected_state = {0: "idle", 1: "charging", 2: "discharging", 4: "disabled"}.get(
        state_raw, "unknown"
    )
    if state != expected_state:
        raise ValueError("bms_state must match bms_state_raw")

    reported_soc = telemetry.reported_soc_percent
    if reported_soc is not None:
        _require_float_range(reported_soc, 0, 100, "reported_soc_percent")
    if (telemetry.soc_source == "bms") != (reported_soc is not None):
        raise ValueError("soc_source must match reported_soc_percent availability")
    _soc_source(telemetry.soc_source)
    if telemetry.soh_percent is not None:
        _require_float_range(telemetry.soh_percent, 0, 100, "soh_percent")

    if not isinstance(telemetry.active_protections, tuple) or any(
        not isinstance(label, str) for label in telemetry.active_protections
    ):
        raise ValueError("active_protections must contain string labels")

    _validate_cell_readings(telemetry.cell_readings)
    slots = telemetry.temperature_slots_c
    if not isinstance(slots, tuple) or len(slots) != 5:
        raise ValueError("Temperature slots must contain exactly five values")
    for index, slot in enumerate(slots, start=1):
        _require_sint(slot, 16, f"temperature slot {index}")
    cell_temp = _require_sint(telemetry.cell_temp_c, 16, "cell_temp_c")
    bms_temp = _require_sint(telemetry.bms_temp_c, 16, "bms_temp_c")
    if cell_temp != slots[0] or bms_temp != slots[1]:
        raise ValueError("cell_temp_c and bms_temp_c must match temperature slots 1 and 2")
    _validate_raw_response(telemetry.raw_response)


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
        cells.append(CellReading(slot, voltage))
    return _validate_cell_readings(tuple(cells))


def _validate_cell_readings(value: object) -> tuple[CellReading, ...]:
    if not isinstance(value, tuple):
        raise ValueError("Cell readings must be stored as an ordered tuple")
    previous_slot = 0
    for cell in value:
        if not isinstance(cell, CellReading):
            raise ValueError("Cell readings must contain CellReading values")
        slot = _as_int(cell.slot, "cell slot")
        voltage = _as_float(cell.voltage_v, "cell voltage")
        if not 1 <= slot <= 16 or slot <= previous_slot or not 0 < voltage <= 65.535:
            raise ValueError("Invalid cell slot ordering or voltage")
        previous_slot = slot
    return value


def _decode_temperature_slots(value: object) -> tuple[int, int, int, int, int]:
    if not isinstance(value, str):
        raise ValueError("Invalid temperature_slots_json value in telemetry database")
    decoded: object = json.loads(value)
    if not isinstance(decoded, list) or len(decoded) != 5:
        raise ValueError("Temperatures must contain five slots")
    slots = [_as_int(item, "temperature slot") for item in decoded]
    return slots[0], slots[1], slots[2], slots[3], slots[4]


def _decode_problem_flags_hex(value: object) -> int:
    if (
        not isinstance(value, str)
        or len(value) != 16
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("Invalid problem_flags_hex value in telemetry database")
    return int(value, 16)


def _validate_raw_response(value: object) -> bytes:
    if not isinstance(value, bytes) or not 101 <= len(value) <= 512:
        raise ValueError("Invalid raw_response; expected a complete frame BLOB")
    return value


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
