# Show balancing, temperatures, and complete problem data in Battery details

Type: task
Status: resolved
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


## Answer

Implemented locally on 2026-11-01. Cell chips use original populated slots;
count/delta remain unchanged. Accessible Battery details shows reference-derived
balancing candidates, unsigned unknown balancing bits, neutral temperature
slots 3–5 including zero/negative values, and unknown low/upper problem hex.
Named protections stay prominent; additional problem data receives a notice
when named protections are clear. Disabled remains the B1 label. Focused
Dashboard/protocol docs describe the implemented behavior.

Validation: sparse-cell browser test failed with C2 before the fix and passed
with C3 afterward. Protocol-details tests failed before implementation and
passed afterward. `uv run pytest tests/test_app.py -q`: 40 passed.
`uv run pytest -m 'not integration' -q`: 185 passed, 2 live tests deselected.
`ty check src/monbat/app.py` and `git diff --check` pass. Broader production
typechecking reports five unresolved Linux-only `dbus_fast` imports in
unchanged `bluez.py` under the macOS environment. No live validation or
deployment was performed.

Code review: Spec found no implementation mismatch; completion bookkeeping
is recorded here and in the map. Standards found no documented violations
and one heuristic about duplicated protocol masks. Kept local presentation
logic under this ticket's existing API contract, with a source comment.
Local identifier/credential scan passed; config.toml and .env.local are ignored.


## Deployment

Deployed `3d40b08` on 2026-11-01 with existing configuration/database. Both
Batteries passed fresh-reading checks; live APIs/SSE, browser rendering, SQLite
integrity, and retained-client release passed. A default-CLI detection gap
required a checked manual graceful stop; follow-up fix is ticket 31.
[Sanitized evidence](../validation/23-20261101-deployment.md).
