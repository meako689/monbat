# Ticket 27: sleep/resume validation after ticket 26

Validate whether [ticket 27](../issues/27-recover-battery-connections-after-laptop-resume.md)
still occurs with ticket 26 installed. Revised on 2026-10-28: the user confirms
ticket 26 is deployed. The primary scenario is Dashboard closed during laptop
sleep, followed by wake and opening the Dashboard to wake collection and Battery
connections. Other scenarios follow only after this scenario is validated.
DEBUG instrumentation is deployed and running. No polling configuration change
or sleep/resume experiment has started.

## 1. Record the setup

Target: `ssh tira@192.168.88.144`, checkout `/home/tira/code/monbat`, service
inside `screen`, Dashboard <http://192.168.88.144:8000/>.

- Identify the screen session, server PID, launch command, working directory,
  interpreter, process start time, source revision and local changes.
- Accept the user's confirmation that ticket 26 is running. Record its revision
  for the evidence; repeating ticket 26 deployment validation is not a gate.
- Record OS/kernel, BlueZ, Bleak and Python versions, adapter identity and
  power state, configured Battery IDs, database path, polling intervals,
  timeout, concurrency, connection persistence and freshness threshold.
- Use the user's normal sleep/wake method on this laptop. The user performs
  sleep and wake, then opens the Dashboard at the agreed point.

Keep the existing background interval for the first primary cycle: opening the
Dashboard should wake collection without waiting for that interval. If waiting
for background baseline passes is costly, the user has authorized temporarily
setting `poller.poll_interval_seconds = 30`. Save the original configuration,
record the effective value, and restart the service once before the baseline
if the change is used. Keep active cadence, freshness, concurrency, persistence
and timeouts unchanged. Do not restart or change configuration between sleep
and the recovery verdict. Restore the original interval after testing and
restart if needed. Report shortened-cadence results as such; they do not establish
recovery timing under the original background interval.

Useful read-only checks include `screen -ls`, process inspection,
`git -C /home/tira/code/monbat status --short`, `git ... rev-parse HEAD`,
`uname -a`, version queries using the service interpreter, and
`bluetoothctl show`. Do not run scans, connect another BLE client, remove
BlueZ devices, or run ticket 26's disconnect harness during this test.

## 2. Prepare evidence before sleep

Read-only inspection on 2026-10-28 found screen session `619154.monbat`, server
PID `619158`, and timestamped output already saved at
`/tmp/monbat-c3ce892.screen.log`. The current background interval is 1800 seconds,
active interval 10 seconds, timeout 10 seconds and freshness 60 seconds;
concurrency is 1 and persistent connections are enabled. Record these again at
the experiment baseline in case they change. The Bluetooth journal query for
the preceding ten minutes returned no entries; this does not establish absence
of Bluetooth problems or the availability of suspend/resume evidence.

The user authorized retaining diagnostic logs in the main code at DEBUG level.
Run `uv run monbat serve --log-level debug` for the physical pass. Logs tagged
`[DEBUG-resume]` cover subscriber counts/disconnection, scheduler wake/admission,
pass start/end, retry deadlines/attempt kind, BLE operation starts/completions,
Telemetry saves and changed SSE snapshots. Operation-start logs locate a stall
even when no failure has been raised yet. Existing WARNING tracebacks remain.
Logging adds no recovery logic; INFO remains the default. Keep the logs in code
and return the service to INFO after the diagnostic session when appropriate.

Create a dated evidence directory on the Linux host. Preserve timestamped
service output, including tracebacks, without injecting input into the running
service. Use existing log output where available; otherwise prepare screen
logging before the baseline. Record any setup changes.

Capture Bluetooth and suspend/resume journal entries from a known start time,
plus adapter/Device1 state before sleep and after resume. If access is denied,
record the missing evidence; do not silently change permissions or services.
Keep capture running on the host so an SSH interruption does not lose it.

Run an HTTP observer from the awake controlling computer. At roughly two-second
intervals, save UTC observation time, HTTP availability, per-Battery Telemetry
timestamp/status from `GET /api/latest`, and summary availability from
`GET /api/summary`. These GETs do not subscribe or trigger collection.
Record transport failures separately from missing Battery updates.

Record Dashboard opening time and its first SSE subscription after wake. Do
not attach any SSE observer while the Dashboard is supposed to be closed: it
would activate collection. After opening, capture browser/SSE updates where
available. The initial snapshot may contain old readings and is not proof of
recovery. Confirm new rows through a read-only database query or history GET.

Record requested sleep, actual OS suspend/resume, network/API return, Bluetooth
readiness, Dashboard opening and first SSE subscription separately. A powered
adapter is a readiness marker, not proof that either Battery is reachable.
Measure each Battery's first saved new reading from resume, Dashboard
subscription and Bluetooth readiness. Record whether background collection
already recovered a Battery before the Dashboard opened.

## 3. Run the primary scenario first

Use the same running service throughout the cycles. Record its PID/start time
before and after each cycle. Require both configured Batteries to update
normally before using a cycle to judge recovery of both; otherwise record a
partial baseline and resolve availability first.

1. Open the Dashboard and obtain at least three successive fresh readings from
   each Battery. This establishes availability and active collection.
2. Close every Dashboard tab and SSE observer, including tabs on other machines.
   Wait beyond the 30-second grace period and confirm retained connections close.
   Record the last readings and any background pass. A background pass is useful
   evidence, but waiting for the default 600-second interval is not required
   to establish that the Dashboard is closed and connections were released.
3. Keep the controlling computer and non-subscribing HTTP observer awake.
   The user sleeps the Linux laptop for 1–2 minutes, then wakes it.
4. As soon as the Dashboard is reachable, the user opens it. Do not wait for a
   background pass or manually refresh collection. Record the actual timing,
   including whether Bluetooth is ready at this point.
5. Confirm the first SSE subscriber wakes collection promptly, without waiting
   for the long background interval. Observe connection/subscription failures,
   cleanup and retries, and verify newly saved Telemetry for each Battery.
6. Require three successive new readings per Battery at the active cadence.
   If recovery is delayed, observe up to five minutes after both the SSE
   subscription and Bluetooth readiness have occurred, extending only when
   recorded operation budgets/backoff justify it. This observation window is
   not a new product SLA. Explain timing using configured active cadence,
   10/20/40/60-second backoff, scan/operation/cleanup budgets and shared-pass delays.
7. Repeat the same closed-Dashboard sequence for a 5–10-minute sleep, or the
   duration that normally triggers the issue, after a stable baseline returns.

If shortened background polling recovers both Batteries before the Dashboard
opens, the cycle demonstrates recovery but does not isolate the Dashboard wake
trigger. Repeat the primary scenario with the original long interval and open
the Dashboard promptly after wake before claiming that trigger is validated.

If recovery fails, preserve the evidence before any manual recovery action.
Record missing attempts, operation failures, cleanup progress, saved timestamps,
and whether a healthy Battery continues updating. Do not reset the adapter or
BMS, manually rediscover, or restart as part of the recovery verdict.

## 4. Additional scenarios after the primary verdict

Only after completing the primary scenario and deciding its next step:

- **Dashboard stays closed after wake:** temporarily use a 30-second background
  interval as authorized above; observe at least two eligible background passes
  and applicable timeout/backoff budgets through GETs and logs. No SSE subscriber
  or POST refresh during this cycle. Record background connect/read/disconnect
  recovery separately from the primary Dashboard-opening scenario.
- **Dashboard open during sleep:** establish retained connections, sleep/wake,
  then observe SSE lifecycle and Battery recovery. Record any subscriber loss
  and resulting mode transition rather than assuming collection stayed active.

Stop adding scenarios if the primary failure needs diagnosis. Other platforms,
longer sleeps and unavailable-Battery stress remain outside this initial pass.

## 5. Pass/fail and the decision

A cycle passes when every Battery available in the baseline automatically
produces and saves post-resume Telemetry, then continues updating at the
appropriate cadence. Confirm the service did not restart. Old timestamps must
remain unchanged during failed reads; status and Bank summary must follow the
configured freshness threshold. The active Dashboard must display new readings
after its event stream reconnects.

For the primary scenario, also establish that opening the Dashboard wakes
collection rather than waiting for the background interval. A background read
that happened before opening is not evidence for this trigger. If logs cannot
establish collection admission, record that limitation and use the next reading
timing or add targeted instrumentation before attributing a delay to BLE.

- **Primary cycles pass:** record that the reported closed-Dashboard → sleep →
  wake → open-Dashboard issue was not reproduced with ticket 26. Record durations,
  per-Battery recovery times and limitations. Do not add a speculative fix or
  claim other platforms/long sleeps were validated. Decide with the user
  whether to run the additional scenarios or close ticket 27 as no longer
  reproducible; an evidence-supported cause has not thereby been established.
- **Battery recovery fails or stalls:** ticket 27 remains claimed. Build a
  repeatable failing loop from the captured scenario, distinguish scheduling,
  BLE setup/read/cleanup and backend availability, then propose the smallest
  supported fix and a Poller-boundary regression test. Repeat the same physical
  cycles after any fix.
- **Telemetry resumes but Dashboard stays stale:** diagnose the event-stream
  or rendering boundary; do not label it a BLE reconnect failure.
- **Deployment, baseline, host resume or adapter readiness cannot be verified:**
  mark the cycle inconclusive and record the exact missing evidence. A single
  successful cycle or an offline simulation is not full physical validation.

Publish a compact per-cycle result table, logs and timestamp series under
`.scratch/monbat/validation/`, linked from ticket 27. Include source identity,
configuration, subscriber lifecycle, sleep duration, first saved post-resume
reading for each Battery, retry/errors, verdict and recovery actions. Update
operational documentation only when verified behavior or limitations warrant it.

Estimated primary session: 5–10 minutes setup/capture, then 15–25 minutes for
two cycles. An additional background cycle at a 30-second interval should take
roughly 5–10 minutes if recovery succeeds. Allow longer for failures or the
user's normal sleep duration. Restore any temporary configuration at the end.

## DEBUG deployment baseline — 2026-10-28

Logging source commit `a70a336` was pushed to origin/master and pulled with
`--ff-only` on the laptop. The old server stopped gracefully. Current screen
session: `619728.monbat`; server PID: `619732`, launched at 22:22:31 +0200 with
`uv run monbat serve --log-level debug`. Current output:
`/tmp/monbat-debug-a70a336.screen.log`, with a one-second screen flush interval.
The old screen log is preserved. Polling configuration remains unchanged.

Startup evidence: shared discovery found both Batteries; bat-1 saved at
22:22:43 +0200 and bat-2 at 22:22:47 +0200. Both clients disconnected, the pass
completed in 18.475 seconds, and the scheduler entered background waiting with
zero subscribers. Dashboard HTTP check on the laptop returned 200.
This verifies logging and normal startup collection, not sleep/resume recovery.

Direct HTTP access from the controlling Mac's Python interpreter returned
`No route to host`, including outside the sandbox, while SSH access and the
laptop's localhost HTTP check worked. Establish a working external observer
before relying on it for the physical test; host-side captures remain available.
