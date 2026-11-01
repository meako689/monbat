# Phase 3: investigate charge/discharge controls

Type: research
Status: open
Triage: needs-triage

## Implementation handoff

Read [the self-contained handoff](../../../docs/protocol/implementation-handoff.md)
for final field names, API/schema contracts, file touchpoints, scope, source
precedence, and verification. It records the final user decisions and
supersedes earlier raw-storage exclusions in historical comments.

## Goal

Plan charge/discharge controls for Phase3. This roadmap ticket replaces the
proposed ATT-mode alignment task; current read-only transport stays unchanged.
Authority: [external command descriptions](../../../docs/protocol/redodo-wire-spec.md#state-changing-and-uncertain-commands).

## Scope

Investigate enable/disable charging MOSFET (0x0A/0x0B) and discharge MOSFET
(0x0C/0x0D). Shutdown, configuration writes, firmware updates, and opcode
sweeps are outside the initial Phase3 scope.

## Acceptance criteria

1. Establish model/firmware-specific command framing, acknowledgements,
   failure behavior, readback verification, and effects on load/charging
   from pinned evidence before writing an implementation plan.
2. Define per-action user confirmation, command serialization with status
   reads, timeout handling, and truthful pending/success/failure presentation.
   A write acknowledgement alone must not be reported as verified switch state.
3. Create reviewable implementation tickets after a separate Phase3 design
   discussion. Research and roadmap scope do not authorize sending controls
   to live Batteries now.
4. Leave the current 0x13 read and response=False transport unchanged.
   ATT write mode is separate from whether a command changes Battery state.

## Validation

Review external evidence and proposed behavior. Physical control validation
requires a separately authorized Phase3 task and explicit confirmation of
its concrete actions. No hardware control execution in this planning ticket.

## Comments

- 2026-10-17: User confirmed charge/discharge controls on the Phase3 roadmap.
  The earlier proposal to change read-query ATT mode was declined.
