import asyncio
import sqlite3
import struct
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from monbat.bms import BatteryTelemetry, CellReading, parse_bms_payload
from monbat.db import TelemetryRepository
from protocol_fixtures import (
    REAL_STATUS,
    captured_status_frame,
    checksum_correct_status_frame,
)


def _telemetry(
    timestamp: float,
    *,
    soc_percent: float | None = None,
    cell_voltages_v: tuple[float, ...] | None = None,
) -> BatteryTelemetry:
    frame = captured_status_frame()
    if cell_voltages_v is not None:
        frame[16:48] = bytes(32)
        for index, voltage in enumerate(cell_voltages_v):
            struct.pack_into("<H", frame, 16 + index * 2, round(voltage * 1000))

    telemetry = parse_bms_payload(
        checksum_correct_status_frame(frame), timestamp=timestamp
    )
    if soc_percent is None:
        return telemetry
    return replace(telemetry, soc_percent=soc_percent)


def _repository(tmp_path: Path) -> TelemetryRepository:
    return TelemetryRepository(str(tmp_path / "telemetry.sqlite3"))


def test_init_db_idempotent(tmp_path: Path) -> None:
    repo = _repository(tmp_path)

    asyncio.run(repo.init_db())
    asyncio.run(repo.init_db())


def test_init_db_enables_wal(tmp_path: Path) -> None:
    db_path = tmp_path / "telemetry.sqlite3"
    asyncio.run(TelemetryRepository(str(db_path)).init_db())

    with closing(sqlite3.connect(db_path)) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

    assert journal_mode == "wal"


def test_save_and_get_latest_preserves_all_fields(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    telemetry = _telemetry(timestamp=123.0)
    asyncio.run(repo.init_db())

    asyncio.run(repo.save_telemetry("bat-1", telemetry))
    result = asyncio.run(repo.get_latest_telemetry("bat-1"))

    assert result == telemetry


def test_save_rejects_balancing_mask_outside_u32_range(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    asyncio.run(repo.init_db())
    invalid = replace(_telemetry(timestamp=123.0), balancing_mask=0x1_0000_0000)

    with pytest.raises(ValueError, match="balancing_mask.*u32"):
        asyncio.run(repo.save_telemetry("bat-1", invalid))

    assert asyncio.run(repo.get_history("bat-1", 0)) == []


def test_save_rejects_problem_flags_outside_u64_range(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    asyncio.run(repo.init_db())
    invalid = replace(_telemetry(timestamp=123.0), problem_flags=-1)

    with pytest.raises(ValueError, match="problem_flags.*u64"):
        asyncio.run(repo.save_telemetry("bat-1", invalid))

    assert asyncio.run(repo.get_history("bat-1", 0)) == []


@pytest.mark.parametrize(
    "stored_value",
    [
        "4",
        "0x0000000000000004",
        "000000000000000A",
        "000000000000000g",
        "10000000000000000",
    ],
)
def test_read_rejects_noncanonical_problem_flags_hex(
    tmp_path: Path, stored_value: str
) -> None:
    path = tmp_path / "telemetry.sqlite3"
    repo = TelemetryRepository(str(path))
    asyncio.run(repo.init_db())
    asyncio.run(repo.save_telemetry("bat-1", _telemetry(timestamp=123.0)))
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE telemetry SET problem_flags_hex = ? WHERE battery_id = ?",
            (stored_value, "bat-1"),
        )

    with pytest.raises(ValueError, match="problem_flags_hex"):
        asyncio.run(repo.get_latest_telemetry("bat-1"))


@pytest.mark.parametrize("stored_value", [-1, 0x1_0000_0000])
def test_read_rejects_balancing_mask_outside_u32_range(
    tmp_path: Path, stored_value: int
) -> None:
    path = tmp_path / "telemetry.sqlite3"
    repo = TelemetryRepository(str(path))
    asyncio.run(repo.init_db())
    asyncio.run(repo.save_telemetry("bat-1", _telemetry(timestamp=123.0)))
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE telemetry SET balancing_mask = ? WHERE battery_id = ?",
            (stored_value, "bat-1"),
        )

    with pytest.raises(ValueError, match="balancing_mask.*u32"):
        asyncio.run(repo.get_latest_telemetry("bat-1"))


def test_save_rejects_incomplete_temperature_slots(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    asyncio.run(repo.init_db())
    invalid = replace(
        _telemetry(timestamp=123.0), temperature_slots_c=(24, 23, 0, 0)
    )

    with pytest.raises(ValueError, match="five"):
        asyncio.run(repo.save_telemetry("bat-1", invalid))

    assert asyncio.run(repo.get_history("bat-1", 0)) == []


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"cell_temp_c": 25}, "cell_temp_c"),
        ({"protection_flags": 5}, "protection_flags"),
    ],
)
def test_save_rejects_inconsistent_telemetry_fields(
    tmp_path: Path, changes: dict[str, int], message: str
) -> None:
    repo = _repository(tmp_path)
    asyncio.run(repo.init_db())
    invalid = replace(_telemetry(timestamp=123.0), **changes)

    with pytest.raises(ValueError, match=message):
        asyncio.run(repo.save_telemetry("bat-1", invalid))

    assert asyncio.run(repo.get_history("bat-1", 0)) == []


def test_save_rejects_cell_readings_out_of_slot_order(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    asyncio.run(repo.init_db())
    invalid = replace(
        _telemetry(timestamp=123.0),
        cell_readings=(CellReading(3, 3.30), CellReading(1, 3.31)),
    )

    with pytest.raises(ValueError, match="cell slot ordering"):
        asyncio.run(repo.save_telemetry("bat-1", invalid))

    assert asyncio.run(repo.get_history("bat-1", 0)) == []


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"cycle_count": -1}, "cycle_count.*u32"),
        ({"bms_state_raw": 0x1_0000}, "bms_state_raw.*u16"),
    ],
)
def test_save_rejects_integer_fields_outside_wire_ranges(
    tmp_path: Path, changes: dict[str, int], message: str
) -> None:
    repo = _repository(tmp_path)
    asyncio.run(repo.init_db())
    invalid = replace(_telemetry(timestamp=123.0), **changes)

    with pytest.raises(ValueError, match=message):
        asyncio.run(repo.save_telemetry("bat-1", invalid))

    assert asyncio.run(repo.get_history("bat-1", 0)) == []


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"voltage_v": 65.536}, "voltage_v"),
        ({"current_a": 2_147_483.648}, "current_a"),
        ({"soc_percent": 100.1}, "soc_percent"),
        ({"remaining_ah": 655.36}, "remaining_ah"),
        ({"capacity_ah": 42_949_672.96}, "capacity_ah"),
        ({"reported_soc_percent": 100.1}, "reported_soc_percent"),
        ({"soh_percent": 100.1}, "soh_percent"),
    ],
)
def test_save_rejects_scalar_values_outside_wire_ranges(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    repo = _repository(tmp_path)
    asyncio.run(repo.init_db())
    invalid = replace(_telemetry(timestamp=123.0), **changes)

    with pytest.raises(ValueError, match=message):
        asyncio.run(repo.save_telemetry("bat-1", invalid))

    assert asyncio.run(repo.get_history("bat-1", 0)) == []


@pytest.mark.parametrize(
    ("column", "stored_value", "message"),
    [
        ("cell_temp_c", 25, "cell_temp_c"),
        ("protection_flags", 5, "protection_flags"),
    ],
)
def test_read_rejects_inconsistent_telemetry_fields(
    tmp_path: Path, column: str, stored_value: int, message: str
) -> None:
    path = tmp_path / "telemetry.sqlite3"
    repo = TelemetryRepository(str(path))
    asyncio.run(repo.init_db())
    asyncio.run(repo.save_telemetry("bat-1", _telemetry(timestamp=123.0)))
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"UPDATE telemetry SET {column} = ? WHERE battery_id = ?",
            (stored_value, "bat-1"),
        )

    with pytest.raises(ValueError, match=message):
        asyncio.run(repo.get_latest_telemetry("bat-1"))


def test_soc_percent_is_stored_without_recalculation(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    telemetry = _telemetry(timestamp=123.0, soc_percent=37.25)
    asyncio.run(repo.init_db())

    asyncio.run(repo.save_telemetry("bat-1", telemetry))
    result = asyncio.run(repo.get_latest_telemetry("bat-1"))

    assert result is not None
    assert result.remaining_ah / result.capacity_ah * 100 != telemetry.soc_percent
    assert result.soc_percent == telemetry.soc_percent


def test_get_latest_returns_none_when_empty(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    asyncio.run(repo.init_db())

    assert asyncio.run(repo.get_latest_telemetry("bat-1")) is None


def test_get_latest_returns_newest(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    older = _telemetry(timestamp=100.0)
    newer = _telemetry(timestamp=200.0, soc_percent=38.0)
    asyncio.run(repo.init_db())

    asyncio.run(repo.save_telemetry("bat-1", older))
    asyncio.run(repo.save_telemetry("bat-1", newer))

    assert asyncio.run(repo.get_latest_telemetry("bat-1")) == newer


def test_get_history_filters_by_time(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    asyncio.run(repo.init_db())

    for timestamp in (100.0, 200.0, 300.0):
        asyncio.run(repo.save_telemetry("bat-1", _telemetry(timestamp)))

    history = asyncio.run(repo.get_history("bat-1", since_timestamp=150.0))

    assert [telemetry.timestamp for telemetry in history] == [200.0, 300.0]


def test_get_history_empty(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    asyncio.run(repo.init_db())
    asyncio.run(repo.save_telemetry("bat-1", _telemetry(timestamp=100.0)))

    assert asyncio.run(repo.get_history("bat-1", since_timestamp=200.0)) == []


def test_cell_voltages_round_trip(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    expected = (3.281, 3.282, 3.28, 3.283, 3.279, 3.281, 3.282, 3.28)
    telemetry = _telemetry(timestamp=123.0, cell_voltages_v=expected)
    asyncio.run(repo.init_db())

    asyncio.run(repo.save_telemetry("bat-1", telemetry))
    result = asyncio.run(repo.get_latest_telemetry("bat-1"))

    assert result is not None
    assert isinstance(result.cell_voltages_v, tuple)
    assert result.cell_voltages_v == expected


def test_nullable_health_and_unknown_bits_round_trip(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    telemetry = replace(_telemetry(123), reported_soc_percent=None,
                        soh_percent=None, soc_source="capacity", bms_state="unknown",
                        bms_state_raw=42, protection_flags=0x80000000,
                        problem_flags=0x80000000,
                        active_protections=("Unknown protection bits: 0x80000000",))
    asyncio.run(repo.init_db())
    asyncio.run(repo.save_telemetry("bat-1", telemetry))
    assert asyncio.run(repo.get_latest_telemetry("bat-1")) == telemetry
    assert asyncio.run(repo.get_history("bat-1", 0)) == [telemetry]


@pytest.mark.parametrize("fixture_name", ["REAL_STATUS", "A1_STATUS"])
def test_parsed_response_survives_persistence(tmp_path: Path, fixture_name: str) -> None:
    from monbat.bms import parse_bms_payload
    from test_bms import A1_STATUS

    frame = REAL_STATUS if fixture_name == "REAL_STATUS" else A1_STATUS
    telemetry = parse_bms_payload(b"stale" + frame + b"trailing", timestamp=123)
    repo = _repository(tmp_path)
    asyncio.run(repo.init_db())
    asyncio.run(repo.save_telemetry("bat-1", telemetry))
    asyncio.run(repo.save_telemetry("bat-1", telemetry))
    assert asyncio.run(repo.get_latest_telemetry("bat-1")) == telemetry
    assert asyncio.run(repo.get_history("bat-1", 0)) == [telemetry, telemetry]


def test_incompatible_schema_is_preserved(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE telemetry (id INTEGER PRIMARY KEY, cell_voltages_json TEXT)")
        connection.execute("INSERT INTO telemetry VALUES (1, '[3.3]')")
    original = path.read_bytes()
    with pytest.raises(ValueError, match="new database path"):
        asyncio.run(TelemetryRepository(str(path)).init_db())
    assert path.read_bytes() == original


def test_incompatible_column_definition_is_rejected_before_wal(tmp_path: Path) -> None:
    path = tmp_path / "wrong-type.sqlite3"
    asyncio.run(TelemetryRepository(str(path)).init_db())

    with sqlite3.connect(path) as connection:
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'telemetry'"
        ).fetchone()[0]
        connection.execute("DROP TABLE telemetry")
        connection.execute(table_sql.replace("raw_response BLOB", "raw_response TEXT"))
        connection.execute("PRAGMA journal_mode = DELETE")

    original = path.read_bytes()
    with pytest.raises(ValueError, match="new database path"):
        asyncio.run(TelemetryRepository(str(path)).init_db())

    assert path.read_bytes() == original


def test_incompatible_primary_key_definition_is_rejected_before_wal(
    tmp_path: Path,
) -> None:
    path = tmp_path / "wrong-primary-key.sqlite3"
    asyncio.run(TelemetryRepository(str(path)).init_db())
    with sqlite3.connect(path) as connection:
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'telemetry'"
        ).fetchone()[0]
        connection.execute("DROP TABLE telemetry")
        connection.execute(table_sql.replace(" AUTOINCREMENT", ""))
        connection.execute(
            "CREATE INDEX idx_telemetry_battery_time "
            "ON telemetry (battery_id, timestamp DESC)"
        )
        connection.execute("PRAGMA journal_mode = DELETE")

    original = path.read_bytes()
    with pytest.raises(ValueError, match="new database path"):
        asyncio.run(TelemetryRepository(str(path)).init_db())

    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "replacement_index",
    [
        None,
        "CREATE INDEX idx_telemetry_battery_time "
        "ON telemetry (timestamp DESC, battery_id)",
    ],
)
def test_incompatible_index_is_rejected_before_wal(
    tmp_path: Path, replacement_index: str | None
) -> None:
    path = tmp_path / "wrong-index.sqlite3"
    asyncio.run(TelemetryRepository(str(path)).init_db())
    with sqlite3.connect(path) as connection:
        connection.execute("DROP INDEX idx_telemetry_battery_time")
        if replacement_index is not None:
            connection.execute(replacement_index)
        connection.execute("PRAGMA journal_mode = DELETE")

    original = path.read_bytes()
    with pytest.raises(ValueError, match="new database path"):
        asyncio.run(TelemetryRepository(str(path)).init_db())

    assert path.read_bytes() == original
