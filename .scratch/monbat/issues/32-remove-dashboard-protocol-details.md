# Remove unhelpful protocol details from Dashboard

Type: task
Status: resolved
Triage: ready-for-agent

## Goal

User requested removal after reviewing ticket 23 live. Remove the Battery
details disclosure, balancing candidates/unknown bits, extra temperature slots,
unknown problem hex, and the associated notice. Preserve original cell-slot
labels, normal named protections, BMS state, and freshness/update behavior.
Keep all protocol data in storage and APIs. This supersedes ticket 23's
Dashboard presentation requirements; no hardware-use conclusion is established.

## Validation

Run app/browser regressions, full offline suite, and changed-module typechecking.
Deploy the Dashboard change using the existing compatible config/database.


## Answer

Removed the protocol disclosure and its additional-problem notice. Original
cell-slot labels, named protections, BMS state, and ordinary readings remain.
Storage/API fields are unchanged. Updated focused docs and recorded the scope
revision in the spec/handoff. Existing browser tests now verify retained state,
protections, escaping, and sparse-cell identity.

Validation: 191 offline tests passed, 2 live tests deselected. Changed app module
typechecking and `git diff --check` passed. Deployment validation follows.
