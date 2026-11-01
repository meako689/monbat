# Decode useful protocol fields and preserve cell identity

Type: task
Status: open
Triage: ready-for-agent

## Implementation handoff

Read [the self-contained handoff](../../../docs/protocol/implementation-handoff.md)
for final field names, API/schema contracts, file touchpoints, scope, source
precedence, and verification. It records the final user decisions and
supersedes earlier raw-storage exclusions in historical comments.

## Goal and authority

Extend typed Telemetry with useful information from the
[external wire spec](../../../docs/protocol/redodo-wire-spec.md#status-response-0x13).
Pinned bmsmon documentation governs the Redodo baseline. A1 and L/E fill
its balancing and temperature gaps with explicitly qualified interpretations.

## Acceptance criteria

1. Preserve original 1-based cell slot numbers in typed cell readings.
   Filter unused zero slots without renumbering later cells. Preserve the
   existing voltage values and compute cell delta from populated readings.
2. Decode all five signed i16 temperature slots at 52–61. Keep existing
   named cell/BMS temperatures; identify additional readings by slot number.
   Preserve 0 °C and do not infer sensor absence from zero values.
3. Decode the u32 balancing mask at 84. Expose candidate balancing cell
   slots from bits 0–15, numbered 1–16, using L's reference-derived meaning.
   Preserve the full mask, including bits without established cell semantics.
4. Decode the entire 76–83 region as a raw u64 problem/failure value. Keep
   existing low-word protection flags and labels. Identify unknown low bits
   and nonzero upper bits explicitly without inventing failure labels.
   The upper word is recoverable from this value; no duplicate field is needed.
5. Keep B1 baseline widths and state names, explicit unknown states, SOC/SOH
   policies, signed current/power, header/length/checksum validation, and
   per-connection serialization. Read every decoded field before the checksum.
6. Retain each complete validated status response as immutable bytes in
   typed Telemetry. Preserve the realigned declared frame, including header,
   all fields/unknown bytes, and checksum; exclude stale prefixes and bytes
   outside its declared length. Store the exact response for every persisted
   Telemetry reading, at whatever cadence the Poller uses. No added fields
   for voltage8, control68, balance memory72, or counter100. Their meanings
   remain documented and deferred. Keep the exact read-only 0x13 query and
   current ATT write mode unchanged; do not add controls.

## Validation

Attributed B4/A1 captures plus focused fixtures for bit63, unknown low bits,
balancing slots 1/3/16 and an unknown high bit, sparse cell slots 1/3,
negative and zero temperatures, and corrupt/truncated frames. Verify slot
identity, useful values, and byte-for-byte recovery of the full response; synthetic fixtures do not validate physical meanings.

## Comments

- 2026-10-17: Grilling confirmed useful typed fields only, no full raw-frame
  storage, fresh database, and unchanged read-only transport.

- 2026-10-17: User revised the storage decision: preserve full validated BLE
  samples alongside useful typed fields. This supersedes the earlier exclusion.
