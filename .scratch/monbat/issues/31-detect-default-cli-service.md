# Detect manually started default-CLI services during deployment

Type: task
Status: resolved
Triage: ready-for-agent

## Goal

User requested this fix after ticket 23 deployment. Detect the service launched
as plain `monbat` or `monbat --log-level LEVEL`, as well as explicit `serve`,
in the configured checkout. Preserve PID start-identity checks, log level,
multiple-server rejection, and graceful shutdown. Exclude discovery and
unrelated Python processes; no service restart is needed for this script fix.

## Validation

Synthetic /proc process records exercise default/explicit CLI forms, log-level
preservation, wrong checkout, discovery, unrelated processes, and changed PID.
Run deployment tests, typechecking, and the full offline suite.


## Answer

Fixed on 2026-11-01 after ticket 23 deployment. Process detection previously
required a `monbat serve` argument pair, missing the equivalent default CLI
launch. It now matches the four service launch forms accepted by `monbat.main()`
and preserves log level, checkout isolation, and PID start-identity checks.
No service restart was performed for this script-only correction.

Validation: synthetic /proc regression first failed for both default forms
(2 failed, 4 passed), then passed after the fix. Deployment tests: 15 passed.
Full offline suite: 191 passed, 2 live tests deselected. Script typechecking and
`git diff --check` passed. Read-only Linux deployment plan recognized one
running service after the fix. Standards and Spec reviews found no findings.
The live incident and safe manual recovery are recorded in
[ticket 23 deployment evidence](../validation/23-20261101-deployment.md).
