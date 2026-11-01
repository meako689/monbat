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
per Battery. Connect consecutive recorded readings across polling gaps and
label every hourly grid line on desktop, as requested in the visual follow-up.

## Acceptance and validation

- Implement the behavior and states in the specification, using existing
  storage/history and browser/app seams.
- Verify navigation, window bounds, recorded values, connections across gaps,
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

### Visual follow-up — 2026-11-01

Added vertical grid lines at each whole local clock hour. Intermediate time
labels align with the grid; narrow layouts use fewer labels to avoid overlap.
Connected readings now use 2px traces without repeated dots. Isolated readings
use small, unoutlined dots; inspecting a reading highlights only that reading.
All recorded values and the strict gap boundary remain available. Updated the
History specification and focused Dashboard documentation. Included in the
chart follow-up deployment recorded below.

### Connected traces and hourly labels — 2026-11-01

The next user follow-up supersedes the original strict gap rule. Every
Battery's consecutive recorded readings now connect, including across polling
gaps. A Battery with a single reading retains its small dot. Desktop labels
every hourly grid line with its two-digit local hour; mobile retains sparse
labels. Removed the unused polling interval from browser chart configuration.
Included in the chart follow-up deployment recorded below.

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

### Visual follow-up validation

- Browser regressions exercise 240 frequent readings across two Batteries,
  one isolated reading, hourly grid placement, non-overlapping time labels,
  keyboard inspection, and one selected marker at a time on desktop/mobile.
  Existing mouse/touch tests also verify the selected marker is visible.
- `uv run --offline --dev pytest -m 'not integration' -q` — 199 passed,
  2 live integration tests deselected.
- `uv run --offline --with ty ty check src/monbat/app.py tests/test_app.py` —
  all checks passed. `git diff --check` passed.
- Inspected synthetic-history screenshots at 1280×720 and 390×844.
- Scanned staged, unstaged, and untracked changes against local identifiers;
  no matches. Confirmed `config.toml` and `.env.local` are ignored by Git.

### Connected traces and hourly labels validation

- Browser tests verify connections across a nondefault polling threshold,
  separate Battery traces, retained single readings, and every desktop hour
  aligned with its grid line. Dense-history tests keep all 242 readings
  available and verify labels do not overlap.
- Offline suite: 199 passed, 2 live integration tests deselected.
- Changed app/test typechecking and `git diff --check` passed.
- Synthetic-history layouts inspected at 1280×800, 768×800, and 390×844.
- Local identifier scan passed; local configuration files remain Git-ignored.

## Deployment

- Chart follow-up: pushed and deployed
  `93d7d43c041422fca2a3fa62f7606d4c4e83eea2` from `0b2241c`.
  Both Batteries produced fresh readings; live connected traces, hourly
  desktop labels, mobile layout, three visible SSE updates, history/storage
  SOC, database integrity, and post-grace connection cleanup passed.
  Configuration/database retained. The next 1,800-second background pass was
  not observed. See [chart deployment evidence](../validation/30-20261101-chart-deployment.md).
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
- 2026-11-01: Reopened and claimed for the requested visual follow-up:
  hourly vertical grid lines and readable markers during frequent updates.
  Resolved locally after implementation, 199 offline tests, typechecking,
  desktop/mobile inspection, and the local identifier scan passed.
- 2026-11-01: Claimed and resolved the next requested follow-up: connect the
  dots across polling gaps and label every hour on desktop. This replaces
  the original strict-gap chart behavior; no collection settings changed.
