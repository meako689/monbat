# 13 Complete BMS frames and expose protection and health Telemetry

Type: task
Status: resolved
Triage: ready-for-agent

## Goal

Apply the existing public Redodo protocol work to our driver, persistence, API,
and Dashboard. Receive complete responses and expose protections, BMS state,
reported SOC, SOH, and cycle count.

## Scope

- `src/monbat/bms.py`: frame reassembly/validation, field widths, typed fields,
  protection decoding, and effective SOC selection.
- `src/monbat/db.py`: fresh schema and round-trip serialization of every field.
- `src/monbat/app.py`: API serialization and Battery-card details.
- `README.md`: fresh-database setup and field meanings.
- Existing fixtures and prototype examples: align them with the new protocol
  contract when needed to keep supported examples usable.

Field offsets, types, protection masks, and pinned sources are authoritative
in [spec section 4.2](../spec.md#42-ble-bms-protocol--driver-srcmonbatbmspy).

## Acceptance criteria

1. Keep the existing read-only `0x13` status request and sequential
   connect/notify/request/disconnect lifecycle.
2. Reassemble fragmented notifications using the response header and declared
   length. A captured 105-byte response must not complete at 66, 80, 100, or
   104 bytes. Realign past prefixed stale fragments and bound the buffer.
3. Validate response identity, declared length, required field coverage, and
   checksum before saving Telemetry. Determine the response checksum from the
   pinned captured fixture; the reference parser does not itself validate it.
   Reject corrupt/incomplete readings while retaining the last valid reading.
4. Decode pack voltage as uint16 at offset 12 and full capacity as uint32 at
   offset 64. Support our 8S/~26 V Batteries; do not apply a 12 V-only bound.
5. Add reported SOC, SOH, cycle count, raw BMS state, decoded state, raw
   protection flags, and active protection labels to typed Telemetry. Preserve
   unknown state values and protection bits instead of presenting them as idle
   or healthy. Keep BMS protection separate from communication failure.
6. Use valid reported SOC (0–100 inclusive) for `soc_percent`. When it is
   unavailable, use the existing bounded capacity-derived calculation and
   record `soc_source`. A valid 0% reading must not trigger fallback. A malformed
   frame is rejected rather than treated as an unavailable SOC field.
7. Persist all added fields in a fresh SQLite schema. Keep async repository
   operations, WAL, and direct effective SOC persistence. Implement no old
   schema migration or old 66-byte parser fallback. Document selecting a fresh
   database path; do not silently erase a database during app startup.
8. Include the fields in latest/history Telemetry serialization. Display active
   protections prominently, explicit BMS state including Disabled/Unknown,
   and SOH/cycle count as secondary details. Keep individual freshness status
   distinct from BMS state. Preserve signed power for net aggregation.
9. No balancing indicator or balancing follow-up is part of this task; the
   reviewed decoder provides no separate balancing-state field. Additional
   commands, BMS controls, connection redesign, and reverse engineering are
   outside this task.

## Validation for implementation

Use the pinned upstream captured response with attribution, plus focused
fixtures for fragmented/prefixed frames, truncation, wrong identity/length,
checksum corruption, 8S voltage, capacity exceeding uint16 centi-Ah, each
protection mask, unknown state/bits, and reported-SOC fallback. Cover fresh
database round trips and latest/history API fields. Synthetic protection bits
check decoding; they do not establish hardware behavior on our Batteries.

## Comments

- 2026-10-17: User replaced public research with implementation improvements
  based on `mkeguy106/bmsmon`. Include every agreed field, start with fresh
  storage, use reported SOC, and omit balancing follow-up.
- Reviewed reference commit: `4534382d00702e14199e2a2aaab50180cf0878ac`.
  Upstream's real capture is from a 12 V/4S Battery; our existing live evidence
  is 24 V/8S. Historical compatibility is waived; correct 8S operation is required.


## Answer

Implemented complete declared-length frame collection, prefix realignment,
header/length/checksum validation, corrected voltage/capacity widths, BMS SOC
with explicit capacity fallback, state/raw state, protection/raw flags, SOH,
and cycle count. The fresh SQLite schema round-trips every field; latest and
history API serialization includes them. Dashboard cards show BMS state,
active protections, SOH, cycles, and SOC source separately from reading status.
The protocol prototype uses the production decoder and Poller.

Response checksum confirmed against the pinned 105-byte capture:
`sum(frame[:-1]) & 0xff == 0x8b`, matching its final byte.

Validation: `uv run pytest -m 'not integration'` — 65 passed, 2 live-hardware
cases deselected. Covered captured/fragmented/prefixed responses, corrupt and
truncated frames, bounded garbage buffers, timeout/write-failure cleanup,
8S voltage, wide capacity, protections and unknown bits/states, SOC fallback,
nullable health round trips, and latest/history fields. `git diff --check` passed.
Live hardware and browser rendering were not exercised. Existing database
files were preserved; README documents selecting a fresh SQLite path.
