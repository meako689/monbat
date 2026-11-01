# SOC History tab

## Problem Statement

The Dashboard shows current Battery status but does not show how charge level
changed during the last day. The owner needs a simple view of each Battery's
SOC over the preceding 24 hours.

## Solution

Add Dashboard and History tabs to the existing web app. Dashboard opens by
default. Entering History loads one chart showing recorded SOC for each
configured Battery over the preceding 24 hours. History stays static until
the user leaves and enters it again.

## User Stories

1. As the owner, I want Dashboard to open by default, so that current Battery
   status remains immediately available.
2. As the owner, I want a separate History tab, so that I can inspect past SOC.
3. As the owner, I want to return to Dashboard, so that I can resume viewing
   current Telemetry.
4. As the owner, I want the preceding 24 hours on one chart, so that I can
   understand recent charging and discharging.
5. As the owner, I want one line per configured Battery, so that I can compare
   their charge levels without selecting Batteries.
6. As the owner, I want named lines with distinct colors, so that I can identify
   each Battery.
7. As the owner, I want a fixed 0–100% SOC axis, so that changes retain a
   consistent visual scale.
8. As the owner, I want local-time labels, so that I can relate changes to my day.
9. As the owner, I want time and SOC values on hover or tap, so that I can
   inspect a recorded reading on a desktop or phone.
10. As the owner, I want History to load when entered, so that its window
    reflects the time I opened it.
11. As the owner, I want History to remain static while open, so that the
    chart does not move while I inspect it.
12. As the owner, I want consecutive recorded readings connected for each
    Battery, so that its charge trend remains visible across polling gaps.
13. As the owner, I want only recorded values, so that missing history does
    not appear as a fabricated SOC value.
14. As the owner, I want isolated readings to remain visible, so that short
    periods of recorded history are still useful.
15. As the owner, I want an empty-history message, so that I can distinguish
    no Telemetry from a chart that failed to load.
16. As the owner, I want loading and failure states, so that I can tell whether
    History is ready to inspect.
17. As the owner, I want the chart to work without external services, so that
    it remains usable off-grid.
18. As the owner, I want tab switching to preserve collection behavior, so that
    viewing History does not interrupt the existing Poller session.

## Implementation Decisions

- Extend the existing self-contained Dashboard document with two accessible
  in-page tabs. Preserve its responsive dark styling and literal rendering
  of configured Battery names. No router or frontend build system is needed.
- Use vanilla JavaScript and an embedded SVG chart. Keep chart logic local;
  do not introduce a chart framework or shared analytics abstraction.
- Reuse the existing history HTTP API with `hours=24` and its chronological
  Telemetry list. Group by configured Battery identity and plot stored effective
  SOC, without recalculating it from capacity. No database or schema change.
- Load history on each transition into History. Selecting the already-active
  tab does not reload it. Keep a fixed 24-hour window for that view, ending at
  entry time; ignore readings outside it. No timer or SSE event refreshes the
  chart or moves its axes.
- Preserve the single existing SSE connection across tab changes. Dashboard
  updates and existing Poller subscription behavior continue independently
  of the static History view. Do not change collection intervals.
- Connect all consecutive recorded readings for the same Battery with straight
  lines, including across polling gaps. A Battery with only one reading keeps
  its dot visible. Polling intervals do not control chart connections.
- Never join lines between Batteries, synthesize zero SOC, or extend a line
  before its first or after its last recorded reading. Lines between recorded
  values do not add synthesized readings or hover values.
- Use a fixed 0–100% vertical axis and browser-local time labels. Hover/tap
  details identify the Battery, timestamp, and recorded SOC. Distinct colors
  and a named legend identify the traces.
- Mark each whole local clock hour with a vertical grid line and label every
  hour beneath its grid line on desktop, using two-digit local hours. Space
  time labels more widely on narrow screens. Draw connected readings as thin
  lines without repeated markers; draw isolated readings as small dots without outlines.
  Highlight a single inspected reading on hover, tap, or keyboard focus.
  Preserve all readings and their details, including frequent updates.
- Show loading, request-failure, and empty states. For no Telemetry in the
  window, show “No readings in the last 24 hours”. A Battery without history
  must not hide another Battery's available trace. A failed request must not
  present a previous chart as a successfully loaded new window; re-entering
  History retries loading.
- Keep all assets local. Update the focused Dashboard documentation when
  implementation lands.

## Testing Decisions

- The user accepted the existing browser/app seam as the main validation
  boundary. Extend the established Playwright tests that route browser HTTP
  requests through the FastAPI test app, with controlled stored Telemetry
  and no live Bluetooth dependency.
- Test observable behavior: tab selection, displayed Batteries, chart values,
  time window, line breaks, hover/tap details, and loading/empty/error states.
  Avoid snapshots of entire HTML or tests coupled to helper functions and
  exact SVG path serialization.
- Cover distinct per-Battery values, literal configured names, zero/100% SOC,
  partial history, isolated readings, and chronological plotting.
- Use a nondefault configured poll interval. Verify all recorded readings
  connect across gaps below, at, and above that interval, with separate Battery
  traces and no extension beyond their first/last readings. Verify desktop
  hourly labels align with each grid line and mobile labels remain readable.
- Verify no history request on initial Dashboard load, one request on History
  entry, no automatic requests or chart movement as time/SSE updates advance,
  and a fresh request/window on re-entry.
- Verify tab changes preserve the existing SSE subscription and Dashboard
  behavior. Cover desktop hover and mobile tap with a readable narrow layout.
- Reuse existing API history tests for chronological output and stored SOC;
  add focused HTTP assertions only if the implementation changes that boundary.
  No new persistence or Poller unit-test seam is needed for this feature.
- Run the offline application/browser regression suite and inspect desktop
  and narrow-screen rendering. Live hardware validation is unnecessary because
  collection behavior is unchanged.

## Out of Scope

- Power/current plots, Battery Bank history, energy totals, charge-session
  detection, alerts, or forecasts.
- Date pickers, custom ranges, zoom, pan, exports, Battery selectors, or an
  automatic/manual refresh control within History.
- Historical cadence reconstruction, timing tolerance, smoothing, aggregation,
  and downsampling.
- Changes to collection, Freshness, retention, storage schema, BLE behavior,
  or deployment configuration values.
- Deployment and unrelated Dashboard protocol presentation work.

## Further Notes

The user confirmed the initial scope on 2026-11-01 and subsequently accepted
the browser/app testing seam.
The user requested hourly grid lines and clearer rendering of frequent updates
later that day; these are presentation changes within the existing recorded
history window.
The next follow-up requested connecting the dots and labeling every hour on
desktop. This supersedes the original strict `poll_interval_seconds` gap rule:
all consecutive recorded readings for each Battery now connect.

The existing history response contains more protocol data than this chart needs.
One request per entry is sufficient for this first version. A compact endpoint
is deferred unless measured performance makes it necessary.

This specification defines the first concrete portion of Iteration 2. Broader
historical graphing remains future work.
