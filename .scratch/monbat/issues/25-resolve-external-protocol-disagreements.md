# Resolve external protocol disagreements before semantic changes

Type: research
Status: open
Triage: needs-info

## Implementation handoff

Read [the self-contained handoff](../../../docs/protocol/implementation-handoff.md)
for final field names, API/schema contracts, file touchpoints, scope, source
precedence, and verification. It records the final user decisions and
supersedes earlier raw-storage exclusions in historical comments.

## Goal

Resolve disputed meanings from external evidence, not current Monbat code.
Use [the source matrix](../../../docs/research/redodo-protocol-sources.md)
and [wire spec](../../../docs/protocol/redodo-wire-spec.md).
This ticket does not block useful-field tickets 21–23.

## Questions and required evidence

- Voltage12: B1/B2/A1 u16 versus L/C/E u32; voltage8 names differ.
- Capacity64: B1/B2/A1 u32 versus L/C/E u16; full versus design capacity.
- Region76–83: u64 problem flags versus protection76 plus failure80.
- State4: Disabled versus charge disabled; state2 interpretations differ.
- Control68: heating versus control/error bits; balancing72/84 physical
  semantics and sensor identities at 56–61.
- Counter96: cycles versus discharge events; counter100 units.

## Acceptance criteria

1. Record firmware/model, pinned sources, and attributed passive captures or
   documented supported-read observations that discriminate each claim.
   Do not use zero upper bytes as proof of width or synthetic values as proof
   of physical semantics.
2. Where evidence remains inconclusive, retain an explicit unknown/disputed
   result in the wire spec. Do not force a universal interpretation.
3. Create separate implementation tickets only for supported semantic changes,
   with evidence and model scope. Do not rename Disabled merely because a
   LiTime source supplies a narrower label.
4. No control commands, opcode sweeps, forced protection activation, or
   additional command implementation are authorized by this research ticket.

## Missing information

The reviewed sources do not supply discriminating model-specific captures
for all questions. Research may proceed with external source inspection;
physical semantic conclusions require suitable evidence.

## Comments

- 2026-10-17: Grilling retained B1 as the Redodo baseline. Width/state
  disagreements do not block useful-field work. Heater/control, second
  voltage, balance memory, and discharged-capacity semantics remain deferred.
  The later user revision adds complete validated response storage alongside
  useful fields. Persisted responses can support later research; record model,
  firmware where known, and source context before inferring physical semantics.
