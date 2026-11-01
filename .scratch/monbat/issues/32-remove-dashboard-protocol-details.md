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


## Deployment attempt

Published candidate `e692089` on 2026-11-01. Plan detected the existing service
on `3d40b08` and compatible unchanged configuration/database. Apply ID
`ticket32-20261101` sent graceful SIGINT, then refused replacement after the
60-second shutdown deadline. Logs report waiting for open connections to close.
Source remains `3d40b08`; candidate was not started. User was asked to close
Dashboard tabs. Retry with a new deployment ID after graceful shutdown completes;
use `--start-stopped` only if process exit is confirmed. Do not force termination.


## Successful deployment

After the user closed Dashboard tabs, the old service exited gracefully.
Retry `ticket32-20261101-retry1` deployed exact `e692089` with the existing
configuration/database. Both Batteries passed fresh-reading checks. Browser
validation confirmed the removed details are absent, three visible updates
per Battery, and no page errors. API fields and SQLite integrity passed.
[Deployment evidence](../validation/32-20261101-deployment.md).

Post-browser validation confirmed both retained clients released and storage
remained unchanged after the grace period, with no service warnings/errors.
