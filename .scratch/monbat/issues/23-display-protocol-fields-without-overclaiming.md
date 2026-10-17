# Show balancing, temperatures, and complete problem data in Battery details

Type: task
Status: open
Triage: ready-for-agent
Blocked by: 22

## Implementation handoff

Read [the self-contained handoff](../../../docs/protocol/implementation-handoff.md)
for final field names, API/schema contracts, file touchpoints, scope, source
precedence, and verification. It records the final user decisions and
supersedes earlier raw-storage exclusions in historical comments.

## Goal

Present useful protocol additions in the Dashboard without unsupported
physical claims. Authority: [wire spec](../../../docs/protocol/redodo-wire-spec.md).

## Acceptance criteria

1. Label populated cells by original 1-based slot number. A missing slot2
   must not turn slot3 into “Cell 2”. Keep existing populated-cell counts/delta.
2. Show candidate balancing cell slots in Battery details, described as a
   reference-derived interpretation rather than hardware-validated behavior.
   Preserve/display unknown balancing bits as hex where nonzero.
3. Show additional temperature readings by neutral slot labels and preserve
   0 °C. Do not claim unverified sensor names or infer absence from zero.
4. Keep named low-word protections prominent. Display unknown low bits and
   nonzero upper problem/failure values explicitly as hex. Clear low flags
   alone must not imply the entire region is clear.
5. Keep state4 “Disabled” for the B1 baseline. Its explanation may note L's
   narrower charge-disabled observation without claiming a universal meaning.
6. Preserve freshness, accessibility, escaping, and local update flow. No
   raw-frame display, heater/control indicator, second voltage, or discharged
   capacity counter. Latest/history APIs and storage are covered by ticket22.

## Validation

Browser cases for sparse cells1/3, balancing1/3/16, unknown balancing bits,
bit63 with clear low flags, unknown low protections, 0 °C, negative additional
temperatures, unknown state, and safe details rendering.

## Comments

- 2026-10-17: Grilling confirmed storage, APIs, and Battery details together.
