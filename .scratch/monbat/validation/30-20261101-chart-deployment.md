# Ticket 30 chart follow-up deployment — 2026-11-01

Deployed `93d7d43c041422fca2a3fa62f7606d4c4e83eea2` from
`0b2241cc7e0c2530554a9d17b74b3ccb4e0421f9` using deployment ID
`ticket30-chart-20261101`. The candidate was pushed to origin before cutover.
The deployment script returned `status: deployed`, selected the exact commit,
and required fresh readings from both configured Batteries. One service was
running before and after cutover. Configuration and the compatible database
were retained; no migration or rollback occurred.

## Live browser and history

- Direct Dashboard access was unreachable. Validation used a bounded SSH
  tunnel, which was closed after the browser closed.
- Dashboard opened by default. Each Battery card displayed three distinct
  reading timestamps through SSE; there were no browser page errors.
- History exposed 1,739 inspectable readings and one connected trace for each
  of the two Batteries. Desktop had 24 hourly grid lines with labels aligned
  beneath each line. Keyboard inspection displayed the recorded reading.
- Inspected live chart screenshots at 1280×800 and 390×844. Mobile retained
  three time labels. The History window stayed fixed across inspection and
  resizing.
- A later API/database check validated 1,745 history rows against stored SOC
  with zero mismatches. Read-only SQLite `quick_check` returned `ok`.

## Subscriber cleanup

After the validation browser and tunnel closed, the service had zero established
HTTP sockets. Both persistent connection starts had matching finishes, including
matching per-Battery counts. There were no warning/error/traceback log lines.
The first cleanup observation caught one finish in progress; the subsequent
observation confirmed both had completed. The final readings were about 29
seconds old, consistent with collection stopping after the subscriber grace
period. The configured background interval is 1,800 seconds; its next pass
was not observed.

## Local validation and privacy

The candidate passed 199 offline tests, with two live integration tests
deselected, changed app/test typechecking, and `git diff --check`. Synthetic
desktop/tablet/mobile layouts were also inspected before deployment.

Local configuration, identifiers, tunnel logs, raw remote output, and live
screenshots remain in Git-ignored local files. Sanitized evidence contains
no private host, address, or credential values.
