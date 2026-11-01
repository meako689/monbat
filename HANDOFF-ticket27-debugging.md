# Monbat ticket 27: next debugging session

Continue ticket 27 from the reproduced physical sleep/resume failure. The next
session should diagnose and simulate the captured failure before choosing a fix.
Validation evidence is saved; no recovery fix has been implemented.

Paths below are relative to the existing `monbat` workspace. Remote access
details remain in the referenced plan rather than being copied here.

## Read first

1. `AGENTS.md` for repository rules, then
   `.scratch/monbat/issues/27-recover-battery-connections-after-laptop-resume.md`
   for status, scope, authorization and the latest result.
2. `.scratch/monbat/validation/27-20261028-cycle1/report.md` for the sequence,
   failing boundary, caveats, evidence links and decision. Start with its
   service-discovery timeout and subsequent cleanup traceback; distinguish the
   observed failure from the still-unproven transport failure mechanism.
3. `.scratch/monbat/plans/27-sleep-resume-validation.md` for the target machine,
   deployment, primary scenario and physical retest procedure.
4. `.scratch/monbat/issues/26-reconnect-with-cached-ble-devices.md` and
   `.scratch/monbat/spec.md` connection-recovery revision for the lifecycle
   contract a fix must preserve. Follow repository pointers for relevant domain
   and operational documentation.

## Next work

- Establish a regression at the real Poller/Bleak boundary using the captured
  setup timeout and unusable-transport cleanup sequence. The recorded-cycle
  evaluator in `27-check-recovery.py` already returns FAIL; it evaluates saved
  physical evidence, not an offline backend reproduction.
- Minimize that regression, then rank falsifiable hypotheses and test them.
  Preserve ticket 26's cleanup ownership and prevention of overlapping clients
  when deciding how recovery can safely proceed.
- Once supported by evidence, implement the smallest fix, run relevant checks,
  and repeat the primary physical scenario with the user. Further sleep
  scenarios were deferred because the primary scenario failed.

The user's primary scenario is closed Dashboard during sleep, then wake and
open Dashboard. The user performs physical sleep/wake. Browser reload occurred
in the recorded cycle; the report explains its timing and limits. For the next
physical pass, establish the exact user steps and record actions again.

## Working state

- Logging implementation and deployment documentation are committed and pushed:
  `a70a336`, followed by documentation commit `9751e3a`. Read the commits/diff for
  implementation details. Collection/recovery control flow was not changed.
- The remote service was left running at DEBUG, with the original polling
  configuration. Current session/PID/log details and deployment checks are in
  the plan and cycle report; recheck live state before operating it.
- The HTTP observer and human prompt harness were stopped/completed. No local
  monitor is still collecting this cycle. Use the curl-based observer for future
  captures; it worked despite earlier direct HTTP failures from Python.
- Ticket 27 and the map contain uncommitted validation updates. The cycle
  directory and three validation scripts are untracked. Preserve and inspect
  them before staging; check whether `.log` evidence is ignored by Git.
- The pre-existing untracked `docs/research/` BLE/reset notes are unrelated to
  this change. Leave them intact and outside any incidental commit.
- The remote checkout had an unrelated untracked `hardcopy.0`; preserve it.

## Authorization and limits

The user authorized DEBUG logging in main code, commit/push, remote pull and
restart at DEBUG; that deployment is complete. Logging should remain in code
behind DEBUG. The user also allowed temporarily shortening background polling
for tests, but the completed cycle used the original configuration.

The immediate request was validation followed by a decision. Do not represent
this handoff as a new deployment approval or a completed fix. Apply ticket 27's
scope for further debugging and the user's next-session instructions for changes.
Adapter/BMS resets and Battery control writes remain outside scope.

## Suggested skills

Call the Skill tool for:

- **mattpocock-skills:diagnosing-bugs**: required next; continue from the saved
  physical failure and build an offline regression rather than starting with a
  speculative fix. Load its instructions afresh in the new session.
- **mattpocock-skills:tdd**: if the user explicitly requests test-first work.
- **writing-for-agents**: if updating agent-facing handoffs or instructions.

If no Skill tool is exposed, read the named skill's `SKILL.md` using the session
skill catalog. No subagents were used; delegate only if the user or an applicable
instruction explicitly requests it.
