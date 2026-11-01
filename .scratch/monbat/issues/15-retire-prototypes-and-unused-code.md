# 15 Retire superseded prototypes and unused code

Type: task
Status: resolved
Triage: ready-for-agent

## Goal

Retire the superseded Dashboard prototype and remove other confirmed unused
code without changing supported behavior.

## Scope

- Remove the Dashboard prototype and redundant BMS prototype from `src/monbat`.
- Preserve historical prototype references as links to fixed Git commits.
- Remove the unused Discovery Script import and BMS service UUID constant.
- Check runtime entry points, request handlers, tests, and documentation before
  removal. Keep currently used code and supported behavior in spec sections
  4.1–4.6.

## Comments

- 2026-10-17: User requested prototype retirement and further unused-code
  removal. This cleanup supersedes ticket 07's preservation constraint for
  its original implementation. The BMS prototype is redundant with current
  parser fixtures and live-hardware tests; neither prototype has runtime or
  test callers.


## Answer

Removed `prototype_dashboard.py` (445 lines) and `prototype_bms_driver.py`
(78 lines), plus the unused `asyncio` import in `discover.py` and unused
`SERVICE_UUID` constant in `bms.py`: 525 source lines removed. Fixed historical
prototype links in tickets 02, 05, and 07 to reference their last Git versions.
Recorded that this cleanup supersedes ticket 07's original preservation scope.

Scanned all Python source and tests for definitions, references, and unused
imports, then checked documentation and entry-point registration. Remaining
production functions have current callers or are FastAPI/CLI entry points.
The BMS parser and live-hardware tests replace the retired simulation and
manual-poll helper. History queries remain used by the supported history
endpoint. No dependencies became unused.

Validation: `uv run pytest -m 'not integration' -q` — 85 passed, 2 live-hardware
cases excluded. All remaining runtime modules import successfully. AST check
found no unused imports in the 9 remaining Python source/test files.
`git diff --check` passed. Live BLE and browser rendering were not exercised.
