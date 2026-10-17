import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path

from monbat.bms import BatteryTelemetry
from monbat.db import TelemetryRepository


def _telemetry(
    timestamp: float,
    *,
    soc_percent: float = 37.25,
    cell_voltages_v: tuple[float, ...] = (3.28, 3.281, 3.279),
) -> BatteryTelemetry:
    return BatteryTelemetry(
        timestamp=timestamp,
        voltage_v=26.24,
        current_a=-1.25,
        power_w=-32.8,
        soc_percent=soc_percent,
        remaining_ah=48.5,
        capacity_ah=100.0,
        cell_temp_c=24,
        bms_temp_c=23,
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
    from dataclasses import replace
    repo = _repository(tmp_path)
    telemetry = replace(_telemetry(123), reported_soc_percent=None,
                        soh_percent=None, soc_source="capacity", bms_state="unknown",
                        bms_state_raw=42, protection_flags=0x80000000,
                        active_protections=("Unknown protection bits: 0x80000000",))
    asyncio.run(repo.init_db())
    asyncio.run(repo.save_telemetry("bat-1", telemetry))
    assert asyncio.run(repo.get_latest_telemetry("bat-1")) == telemetry
    assert asyncio.run(repo.get_history("bat-1", 0)) == [telemetry]
