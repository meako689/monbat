# Protocol implementation handoff: tickets 21–23

The user confirmed this scope on 2026-10-17, then revised it to preserve
complete BLE responses. This document records the final contract. No driver
changes have been implemented yet. Read the root repository guidance, claim
each ticket before work, and record results/validation when resolving it.

## Read first and authority

- [Wire specification](redodo-wire-spec.md): pinned external sources define
  wire facts. B1 bmsmon documentation governs the Redodo baseline; A1/L/E
  fill gaps with explicitly qualified interpretations.
- [Source comparison](../research/redodo-protocol-sources.md): conflicts and
  pinned implementations. The cited GitHub revisions are immutable references.
- [Project specification section 4.2](../../.scratch/monbat/spec.md#42-ble-bms-protocol--driver-srcmonbatbmspy).
- [Implementation overview](redodo.md), [configuration/storage](../operations/configuration.md),
  and [Dashboard operations](../operations/dashboard.md).

Implement [21](../../.scratch/monbat/issues/21-preserve-complete-status-regions.md),
then [22](../../.scratch/monbat/issues/22-round-trip-protocol-evidence.md),
then [23](../../.scratch/monbat/issues/23-display-protocol-fields-without-overclaiming.md).
An intermediate ticket may update callers/fixtures to keep the repository
working; later tickets still own full persistence/API/UI acceptance.
[T24](../../.scratch/monbat/issues/24-phase-3-charge-discharge-controls.md) is
future Phase 3 planning. [T25](../../.scratch/monbat/issues/25-resolve-external-protocol-disagreements.md)
is evidence research and does not block 21–23.

## Final scope

Add balancing candidate cells, all five temperature slots, full problem/failure
region, stable cell identities, and complete-response storage. Start a fresh
database. Keep the exact read-only `0x13` status query, ATT `response=False`, scheduling,
concurrency, retained connections, freshness, SOC/SOH policy, and signed power.
No history migration, database deletion, additional read commands, or controls.
Do not add interpreted voltage 8, heater/control 68, balance-memory 72, or
counter 100 fields; their bytes remain recoverable from the stored response.

## Typed and API contract

Keep existing scalar Telemetry fields and low-word `protection_flags`.
Use immutable concrete models and these additional fields:

| Field | Python value | JSON value / behavior |
|---|---|---|
| `cell_readings` | tuple of frozen `CellReading(slot: int, voltage_v: float)` | array of `{slot, voltage_v}` objects; populated slots only, ascending 1–16 |
| `temperature_slots_c` | tuple of five ints | five-element integer array; index 0 is slot 1, indices 2–4 are additional temperatures |
| `balancing_mask` | int, u32 | nonnegative JSON integer; exact within JS number precision |
| `problem_flags` | int, u64 | 16-digit lowercase hex string, no `0x` prefix |
| `raw_response` | bytes | omit from latest/SSE; history exposes `raw_response_hex` as lowercase hex, no prefix |

Expose `balancing_cell_slots` as a derived array of 1-based slots for mask
bits 0–15, including slots whose cell voltage is absent. Do not manufacture
voltage readings for such cells. Bit 0 maps to slot 1. Bits 16–31 remain unknown.
Keep existing `cell_voltages_v` output as the compact ordered voltage array
for compatibility; derive it from `cell_readings`, avoiding two independently
mutable sources of cell values. Dashboard labels use `cell_readings`.
Keep named `cell_temp_c`/`bms_temp_c` aligned with temperature slots 1/2.

Unknown low protection bits are `low32 & ~0x4fe4`; the upper problem/failure
word is `problem_flags >> 32`. The upper word's physical interpretation is
unresolved. Render it as hex, never a named protection or proof of shutdown.
Avoid JavaScript bitwise operations on the full u64; use its hex string or
BigInt internally and never JSON-serialize BigInt. For u32 masks, avoid signed
bitwise display errors on bit 31; use unsigned conversion or integer arithmetic.

The balancing interpretation is source-derived, not validated physical
behavior on the user's Batteries. Label extra temperatures by slot number.
Zero °C is retained; no sensor-presence inference from zero. Empty cell slots
are omitted, but populated later cells retain their original numbers.

## Parsing and response boundaries

In [bms.py](../../src/monbat/bms.py), `_validated_frame()` already returns the
realigned frame slice. Preserve that exact bytes object in `raw_response`:
header, unknown fields, and checksum included; stale prefix and unrelated
trailing bytes excluded. Keep declared-length and additive-checksum validation.
Retain every valid persisted response, including identical consecutive frames.
Failed polls never produce a stored sample or replace the last valid reading.

Offsets: cells 16–47 (16 little-endian u16 mV slots), temperatures 52–61
(five little-endian i16 °C slots), problem 76–83 (little-endian u64),
balancing 84–87 (little-endian u32). Existing minimum 101 bytes covers fields
through 99 plus checksum; do not require 105 solely to preserve raw responses.
Never decode checksum bytes as missing fields. The pinned 105-byte fixture
and its expected values are reproduced in the wire spec.

## SQLite and API implementation

In [db.py](../../src/monbat/db.py), add:

- `cell_readings_json TEXT NOT NULL`: slot/voltage objects.
- `temperature_slots_json TEXT NOT NULL`: all five signed readings.
- `balancing_mask INTEGER NOT NULL`: u32 fits SQLite's signed 64-bit integer.
- `problem_flags_hex TEXT NOT NULL`: fixed 16-digit lowercase hex.
- `raw_response BLOB NOT NULL`: exact validated response bytes.

Do not store redundant balancing candidate arrays or duplicate cell voltage
arrays in the fresh schema; reconstruct compatibility values from typed cells.
Validate persisted values at the repository boundary, including hex width,
integer ranges, slots/ordering, and temperature count. Downstream code trusts
those typed models. Do not reparse frames on every ordinary repository read.
Round-trip all new fields in latest and history repository queries.

Inspect an existing telemetry schema before applying DDL/WAL changes. A
mismatch must fail clearly with instructions to select a new database path.
Do not create a partially upgraded schema, mutate old rows, or delete files.
Use a simple complete-column/schema check; no migration framework is needed.

In [app.py](../../src/monbat/app.py), replace unconditional Telemetry `asdict()`
use at the JSON boundary with an explicit serializer. Current latest wraps
`asdict(view)` and history updates rows with `asdict(telemetry)`; both need
attention. Latest and SSE must omit `raw_response`; history emits its hex.
All paths must convert u64 problem flags to the string contract above.
Preserve existing endpoint envelopes, timestamps, battery IDs, history ordering,
status, cell delta, and summary behavior. No new endpoint is required.

## Dashboard and docs

Update the existing Battery details/update flow in app.py, without introducing
another page or external assets. Use original slot numbers, balancing candidate
slots, neutral additional-temperature labels, unknown balancing bits, and
unknown low/upper problem values. Keep named protections prominent. Freshness
is independent of BMS state. Keep Disabled as the B1 label; no automatic rename.
Do not display full raw frames in Dashboard.

Update focused storage/API/protocol implementation docs after behavior changes.
Keep the wire spec's external facts distinct from implemented feature coverage.
README stays quick start plus documentation links.

## Verification and completion

Relevant tests: [test_bms.py](../../tests/test_bms.py),
[test_db.py](../../tests/test_db.py), [test_app.py](../../tests/test_app.py),
and [test_collection.py](../../tests/test_collection.py). Update all realistic
Telemetry constructors; do not synthesize fake raw responses in production
model defaults. Use attributed captured frames and checksum-correct synthetic
variants for edge cases. Synthetic cases verify code, not physical semantics.

Required coverage:

- Full capture bytes survive parser → SQLite → history hex exactly.
- Prefix/trailing garbage is excluded; malformed frames remain rejected.
- Sparse cell slots 1/3 keep identity; delta ignores unused slots.
- Temperatures include zero and negative values in all additional positions.
- Problem bit 63, unknown low bits, balancing bit 31, and candidate slots 1/3/16
  survive storage/API without signed overflow or JS precision loss.
- Clear low flags with nonzero upper word displays unknown problem data.
- Latest/SSE remain JSON serializable and contain no raw response.
- Existing database mismatch leaves original schema/rows intact.
- Existing polling/SOC/summary/freshness behavior remains covered.

Run `uv run pytest -m 'not integration'` and `git diff --check` after the
integrated change. Browser tests require installed Chromium; use the documented
Playwright setup if needed. Do not claim live validation without executing it;
normal read-only smoke tests are separate from any future control validation.
Record actual results in each resolved ticket and update the map.

The 10-minute storage estimate did not change collection timing. Responses are
saved on every successful persisted reading: normally background 600-second
cadence and active 10-second cadence. For two Batteries, 105-byte payloads alone
use about 11 MB/year at 10-minute intervals, or 662 MB/year if active every 10 seconds
continuously; SQLite overhead and typed fields add space. No retention policy
or sample decimation was requested.
