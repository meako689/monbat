# Persist useful protocol fields and expose them through APIs

Type: task
Status: open
Triage: ready-for-agent
Blocked by: 21

## Implementation handoff

Read [the self-contained handoff](../../../docs/protocol/implementation-handoff.md)
for final field names, API/schema contracts, file touchpoints, scope, source
precedence, and verification. It records the final user decisions and
supersedes earlier raw-storage exclusions in historical comments.

## Goal

Round-trip ticket 21's useful typed fields through a fresh SQLite schema and
latest/history APIs. Authority: [wire spec](../../../docs/protocol/redodo-wire-spec.md).

## Acceptance criteria

1. Persist cell readings with original slot numbers, all temperature slots,
   balancing mask, and the full problem/failure region. Candidate slots are
   derived as specified in the handoff.
   Also persist the complete validated response from ticket21 as a SQLite
   BLOB on the same Telemetry row. No separate deferred-field columns are
   required; full response bytes retain those regions for future decoding.
2. Store the unsigned u64 problem/failure region as 16-digit hexadecimal
   TEXT. Use a fixed-width hex string in APIs to avoid SQLite signed-integer
   limits and JavaScript precision loss. Keep low protection fields compatible.
3. Latest/history expose new useful fields and slot identity consistently.
   Include the complete response as hex in history output for retrieval and
   later research. Keep it out of repeated latest/SSE payloads and Dashboard
   rendering, which use typed fields. Derive
   balancing slots from the mask rather than persisting redundant lists.
   Build serialization from repository-defined typed models directly.
4. Start with a fresh database; no historical migration. Preserve existing
   files. Incompatible schema receives an actionable fresh-path error instead
   of being silently reused or deleted. Document fresh database setup.
5. Preserve effective SOC, signed Battery Bank totals, WAL, and async access.
   Update focused schema/API documentation.

## Validation

Fresh SQLite/latest/history round trips for bit63, balancing high bits,
sparse slot identities, 0 °C and negative temperatures. Check incompatible
schema errors preserve the original database file. Verify byte-for-byte BLOB
recovery and history hex against the attributed capture, including checksum
and unknown bytes; prefixes/trailing unrelated bytes must not be stored.

## Comments

- 2026-10-17: User confirmed fresh database and useful fields only after grilling.

- 2026-10-17: User revised the decision to preserve full BLE samples as BLOBs
  alongside useful fields. Fresh-database policy remains unchanged.
