# Ticket 21 Linux deployment plan

Deploy commit `f94e072` with a fresh protocol Telemetry database. Preserve the
current configuration, historical database, and rollback source. This document
plans the rollout; it does not execute a push, remote change, or restart.

## Candidate and baseline

- Candidate: `f94e072`, ticket 21. Local validation: 143 offline tests passed;
  the changed production modules pass typechecking; both review axes pass.
- Last recorded Linux application revision: `aaf7a80`, deployed for ticket 28.
  This is a recorded baseline, not a fresh inspection of the running host.
- Ticket 22 remains open for complete persistence-boundary and storage/API
  edge-case acceptance. This rollout is a bounded ticket-21 hardware smoke
  test, not completion of tickets 22–23. Dashboard presentation of new protocol
  details remains pending ticket 23.
- Expected user-visible change: history begins at cutover in the new database.
  Old history remains in the preserved database and is not merged or migrated.
  Cards initially have no readings; Battery Bank totals become available after
  all configured Batteries have fresh successful readings.

## 1. Read-only preflight

Load ignored `.env.local` before remote commands. Resolve the SSH target,
checkout path, and Dashboard URL from it; never copy live values into this plan
or committed evidence.

1. Identify the actual service process, screen session, working directory,
   launch command, interpreter, log destination, source revision, and Git status.
   Do not assume an old PID or session is still current.
2. Record the original `sqlite_path`, effective polling configuration, configured
   Battery IDs, current API availability, last reading timestamps, and disk space.
   Keep Battery addresses, private URLs, and raw captures in ignored local files.
3. Confirm both Batteries are available using the existing service. Use ordinary
   GETs for observation. If a Dashboard/SSE subscription is used for the baseline,
   close it and wait beyond the 30-second grace period before cutover.
4. Confirm a clean remote checkout or account for local edits before advancing
   it. Record the exact rollback revision, not merely the recorded baseline.
5. Confirm the candidate is available from origin. If it is not, publishing it
   is an execution step. Fetch and inspect before changing the running source.
   Verify the intended candidate and ancestry; do not deploy an unspecified
   newer branch tip. Run `uv sync --locked` for the candidate before service start.
6. Choose a unique new database path in persistent private storage outside tracked
   artifacts (for example under the user data directory, never `/tmp`). An absolute path
   avoids working-directory ambiguity. Verify it does not exist and its parent
   is writable. Confirm the selected path and evidence directory are ignored by
   Git or outside the checkout. Do not delete a file to reuse its name.

Stop preflight if source identity, rollback source, configuration, or the new
path cannot be established. An unavailable Battery makes the two-Battery smoke
test inconclusive; record that baseline rather than attributing it to the update.

## 2. Preserve rollback and cut over

1. Save the original config and launch details in a private host-local directory.
   Keep an accessible checkout of the exact previous revision for rollback.
   Preserve its dependency lockfile and ability to recreate its environment.
2. Stop the identified service gracefully with SIGINT. Wait for shutdown and
   bounded BLE cleanup, then confirm the old server exited and released its port.
   Do not launch two Pollers against the Batteries. If cleanup is unresolved,
   preserve the logs and investigate before proceeding.
3. Preserve the original database in place. Make a consistent SQLite backup
   through SQLite's backup API after the writer has stopped. Do not copy only
   the main file while ignoring a possible WAL. Record backup completion and
   integrity; leave original database and sidecars intact.
4. Advance the clean checkout to the verified candidate using a fast-forward
   where possible. Avoid reset/clean commands that discard local files. If the
   candidate cannot be selected cleanly, use a separate checkout with its own
   environment and the preserved local configuration.
5. Change only `poller.sqlite_path` in ignored `config.toml` to the new path.
   Preserve names, addresses, cadence, concurrency, persistence, freshness,
   timeouts, and server settings. Do not run rediscovery.
6. Start one detached service through the existing screen arrangement with
   timestamped logging. Retain the current diagnostic log level for continuity
   with ticket 27; do not change it incidentally. Record PID, start time,
   candidate revision, working directory, and effective configuration.

## 3. Validate before accepting the rollout

Use live read-only status polling. Do not run a second direct BLE test client,
reset the adapter/BMS, or issue control commands.

### Startup and background pass

- Confirm startup creates the fresh schema, HTTP returns 200, and no schema,
  SQLite, or JSON serialization error appears.
- With no SSE subscribers, confirm one shared discovery serves the startup
  background pass, each baseline-available Battery saves new Telemetry, clients
  close, and the pass completes. An initially empty latest response is expected;
  a persistent empty response after the completed successful pass is not.
- Confirm the selected database is the new file, the old database remains
  untouched by the candidate, and the new file has WAL mode and required columns.

### Protocol persistence and HTTP output

For at least one saved reading per available Battery:

- Match history output to the stored row by Battery ID and exact timestamp.
- Verify `raw_response` is a nonempty SQLite BLOB and history
  `raw_response_hex` decodes to exactly those bytes. Independently verify header,
  declared frame length, additive checksum, and that decoded useful fields
  agree with the returned Telemetry. Do not assume every frame is 105 bytes.
- Check original ordered cell slots, populated voltages, five signed integer
  temperatures including zero, unsigned u32 balancing mask, candidate slots,
  and exactly 16 lowercase hex digits for the u64 problem region.
- Verify latest and SSE contain neither `raw_response` nor
  `raw_response_hex`; both must remain JSON serializable. History alone exposes
  the response hex. Check signed current/power, effective SOC, freshness, cell
  delta, and Battery Bank totals against the same fresh readings.
- Keep captured values and full responses in ignored private evidence. Report
  balancing as reference-derived candidates; this smoke test cannot establish
  physical balancing or extra sensor identities from nominal readings.

### Active Dashboard and return to background

1. Open one Dashboard or one bounded SSE observer. Confirm the subscription
   wakes collection and both Batteries produce at least three successive new
   readings at the configured active cadence, allowing scan/operation time and
   skipped slots. Confirm retained connections are reused when enabled.
2. Confirm existing cards, temperatures, protections, SOC, signed power, and
   summary still render and update without console or HTTP errors. New details
   are not required in the UI until ticket 23.
3. Close all subscribers. After the grace period, confirm retained clients close
   and collection returns to background mode. Non-subscribing latest/history
   GETs must not reactivate collection.
4. Observe the next scheduled background pass at the original interval when
   practical. If that interval is long, accept the bounded startup/active smoke
   test separately and explicitly leave long-cadence observation pending.
   Do not shorten polling configuration for this rollout.

Accept the bounded deployment smoke test only when each baseline-available
Battery has saved valid responses, storage/history agree exactly, latest/SSE
serialize correctly, and the Dashboard updates. Record failures and missing
observations without claiming full ticket-22 acceptance or sleep/resume recovery.

## 4. Rollback

Rollback triggers: startup/schema failure, repeated new persistence or JSON
errors, invalid stored responses, or loss of baseline Battery updates linked
to this candidate. Preserve diagnostic evidence before changing the service.

1. Stop the candidate gracefully and confirm process/port release.
2. Preserve the new database and logs for diagnosis; do not delete them.
3. Restore the saved original configuration, especially the old `sqlite_path`.
4. Start the exact previous source revision with its lockfile/environment and
   original launch settings. An isolated rollback checkout avoids overwriting
   the candidate or unrelated edits. Never point the old code at the new schema.
5. Verify HTTP, new readings from baseline-available Batteries, and Dashboard
   updates. Record the rollback revision and resulting timestamps.

Rows collected after cutover stay in the new database after rollback. They are
not automatically visible to the old service. Old history resumes from the old
file; do not merge the databases during incident recovery.

## 5. Evidence and follow-up

Record candidate and previous revisions, cutover time, process identity,
configuration change limited to database path, backup integrity, per-Battery
first saved timestamps, protocol/storage/API checks, subscriber lifecycle,
errors, and verdict. Publish a sanitized summary under
`.scratch/monbat/validation/` and link it from ticket 21. Keep credentials,
private identifiers, full captures, config backups, and unsanitized logs ignored.
Scan staged/unstaged/untracked evidence before committing.

Expected hands-on window: about 10–20 minutes if both Batteries are available
and environment setup is ready. Scheduled background observation adds the
actual configured interval and operation time. Ticket 27's physical Linux
sleep/resume validation remains a separately coordinated session using its
existing plan. Ticket 22 remains the next implementation task.
