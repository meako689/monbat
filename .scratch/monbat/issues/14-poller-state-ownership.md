# 14 Concentrate Poller state ownership

Type: task
Status: resolved
Triage: ready-for-agent

## Goal

Put refresh admission and sequential polling in one Poller module with private
scheduling state. Preserve spec section 4.5 behavior.

## Scope

- Add `src/monbat/poller.py`; replace `PollerRefresh` and `run_poller_task`.
- Keep typed configuration, parsing, task creation, cancellation, and awaiting
  in `app.py`. No scheduler framework or additional abstraction.
- Test admission through requests rather than assigning internal state.
- Retain startup, concurrent admission, exact cooldown, failure recovery,
  background delay, and shutdown coverage.

## Comments

- 2026-10-17: User confirmed this structure after the architecture review and
  grilling. Existing polling behavior remains the contract.


## Answer

Added `src/monbat/poller.py` with one `Poller` owning refresh admission,
sequential polling, and private scheduling state. Removed `PollerRefresh` and
`run_poller_task` from `app.py`. The lifespan creates a fresh Poller, cancels and
awaits its task, and clears its reference before shutdown. Configuration types
and parsing remain in `app.py`; Poller imports the configuration type only for
static typing, avoiding a runtime import cycle. No new dependencies or generic
scheduler abstraction were added.

Tests now exercise failure recovery and concurrent admission through the app.
They cover startup reservation, twenty simultaneous refresh requests, exact
30-second eligibility, one active BLE call, cancellation, disabled requests,
retained successful timestamps after failures, and background operation. Added
a check that background delay restarts after a refresh finishes. Poller clock
patching is local to its module and does not alter asyncio's clock.

Validation: `uv run pytest -m 'not integration' -q` — 85 passed, 2 live-hardware
cases excluded. `git diff --check` passed. No live BLE validation was performed.
The behavior contract is unchanged; spec sections 4.4–4.5 record the structure.
