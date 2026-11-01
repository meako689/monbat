# Use one shared scan for background collection

Type: task
Status: resolved
Triage: ready-for-agent

## Problem

Long background gaps leave cached BLEDevice objects pointing at missing BlueZ
objects. The November 1 diagnosis found every post-startup scheduled background
pass first failed, then rediscovered after backoff. Slightly different retry
deadlines can also cause two scans for almost simultaneous recovery.

## Approved scope

The user approved replacing long-run discovery caching on November 1:
"ditch the caching for long runs. do a single scan that can be re-used.
Cached connections for the dashboard re use."

- Each background collection or recovery pass uses one shared discovery for
  eligible Batteries requiring a new connection. Reuse those fresh results
  for all connections in that pass; never retry an old discovery object first.
- Reuse healthy retained Dashboard connections without scanning. Preserve
  existing recent cached reconnects within active collection and its grace
  period. Clear disconnected discovery candidates when returning to background,
  so Dashboard opening after a long idle gap starts with fresh discovery.
- Include failed Batteries whose retry becomes eligible during a background
  scan, using that same result. Do not shorten backoff, reconnect cleanup-pending
  clients, collect healthy Batteries early, or attempt a Battery twice per pass.
- Preserve confirmed cleanup, bounded operations, retry cadence, persistence
  handling, request concurrency, response isolation, and accurate Freshness.
- Update focused docs and recovery contracts. This revision supersedes ticket
  26's service-lifetime/background cache requirement; ticket 27's physical
  sleep/resume validation remains separate and pending.

## Acceptance and validation

- Several long background cycles save available Batteries on the scheduled
  pass, with one scan per pass and fresh BLEDevice results.
- Nearly simultaneous failed Batteries share one background recovery scan,
  including when the second retry matures during scanning.
- Dashboard reads reuse retained clients; a new Dashboard session after idle
  uses fresh discovery. Pending cleanup prevents replacement.
- Existing active cached recovery, backoff, scheduler, driver, API/SSE, and
  Dashboard regressions pass after updating superseded background expectations.
- Promote the actual missing-object diagnostic seam into a permanent regression
  before changing production behavior. Re-run the original diagnostic replay.

## References

- [November 1 diagnosis](../validation/27-20261101-cache-diagnosis/report.md)
- [Recovery specification](../../monbat-recovery/spec.md)
- [Collection specification](../spec.md)

## Comments

- 2026-11-01: Claimed for implementation after user approval. No deployment or
  Bluetooth experiment is included in this change.

## Answer

Implemented locally on 2026-11-01. Background collection and retry passes share
one fresh scan instead of trying service-lifetime discovery objects first.
Failed Batteries whose deadlines mature during the scan reuse its results;
healthy and cleanup-pending Batteries are excluded. Background cleanup and the
active-to-background transition discard disconnected candidates. Active/grace
collection retains existing connection and recent-candidate reuse.

Validation:

- New permanent regressions first produced three failures and one passing
  future-deadline control before the fix. They now pass for repeated long-gap
  cycles, deadlines maturing during discovery, backoff preservation, and
  Dashboard opening after idle followed by retained-client reuse.
- `uv run --group dev pytest -m 'not integration' -q`: 133 passed, two live
  tests deselected. Superseded background-cache expectations were updated;
  active cache fallback, cleanup, scheduling, driver, API/SSE, and browser
  coverage remain passing.
- The [original diagnostic replay](../validation/27-20261101-cache-diagnosis/diagnostic_repro.py)
  passes against the fix: zero cached-attempt backoff and one scan for both
  Batteries, completing in 18 simulated seconds. The identical replay fails
  both cases against the pristine HEAD Poller restored in a temporary snapshot:
  10-second backoff and two recovery scans, completing in 38 simulated seconds.
  These timings describe controlled external fakes, not a hardware benchmark.
- `git diff --check` passed. Changed staged/unstaged/untracked text was scanned
  for live local identifiers; local configuration and captures remain ignored.

Focused operational/protocol docs and the collection/recovery specifications
now describe the approved reuse boundary. No deployment, live Bluetooth action,
or physical performance/sleep test was performed. Ticket 27 remains claimed
until its separate physical validation is complete.
