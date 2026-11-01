# Implement the SOC History tab

Type: task
Status: resolved
Triage: ready-for-agent
Blocked by: 29

## Problem

The Dashboard has no view of Battery SOC over time.

## Scope

Implement the confirmed [SOC History specification](../../monbat-history/spec.md).
Add Dashboard/History tabs and a static last-24-hours SOC chart with one trace
per Battery. Break traces at gaps greater than the loaded deployment's
`poll_interval_seconds`, with no tolerance.

## Acceptance and validation

- Implement the behavior and states in the specification, using existing
  storage/history and browser/app seams.
- Verify navigation, window bounds, recorded values, configured gap thresholds,
  hover/tap, empty/error states, and no History auto-refresh.
- Preserve SSE collection and Dashboard behavior across tab changes.
- Run offline regressions and inspect desktop/mobile chart rendering.
- Update focused Dashboard documentation and record validation here.

## Answer

Added accessible Dashboard/History tabs to the existing page. History fetches
the existing `/api/history?hours=24` endpoint on entry, plots stored effective
SOC in an embedded SVG over a fixed 24-hour window, and remains static until
re-entry. It uses configured Battery colors/names, local-time labels, a fixed
0–100% axis, and a strict `poll_interval_seconds` gap boundary. Isolated
readings, loading, empty, and failure states are preserved. Tab changes keep
the one SSE connection and Dashboard updates active. Storage, APIs, BLE, and
collection timing are unchanged.

## Validation

- Browser/app regression tests cover default and keyboard tab navigation,
  lazy load, static History, re-entry, SSE continuity, configured strict gap
  boundaries, window filtering, isolated readings, escaping, loading/empty/error
  states, and desktop hover/mobile tap.
- Offline suite: `uv run --offline --dev pytest -m 'not integration' -q` —
  197 passed, 2 live integration tests deselected.
- Typechecking: `uv run --with ty ty check src/monbat/app.py tests/test_app.py` —
  all checks passed.
- Visual inspection: desktop at 1440×1000 and mobile at 390×844; chart scale,
  labels, legend, and narrow layout inspected.
- `git diff --check` passed. Standards review found no documented-rule
  violations; the history-window snapshot is passed as one value, and shared
  test-app request forwarding now uses one helper. Spec review found no
  behavior mismatch or scope creep.

## Deployment

- Deployed `0b2241cc7e0c2530554a9d17b74b3ccb4e0421f9` from
  `fe26b333b3c50857b3ba4ea7f36086b32107823e`. The deployment script returned
  `status: deployed` after fresh readings from both Batteries; configuration
  and database were retained. Browser validation and post-grace connection
  cleanup passed. Long background cadence was not observed. See the
  [deployment evidence](../validation/30-20261101-deployment.md).

## References

- [Design interview](29-charging-history-tab.md)
- [Project specification](../spec.md)

## Comments

- 2026-11-01: Published from the confirmed design using the to-spec skill.
  The user accepted the existing browser/app test seam. Ready for implementation;
  no application code or deployment changes are part of this specification task.
