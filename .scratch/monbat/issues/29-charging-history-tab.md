# Charging history tab for the last 24 hours

Type: grilling
Status: resolved
Triage: ready-for-agent

## Request

Add a basic analytics view with a charging plot for the last 24 hours,
accessible as a separate tab in the web app. Keep the solution simple.
Use the local tracker and grill the design before implementation.

## Decisions pending

- None. The user confirmed the complete scope.

## Decisions so far

- SOC (%) over the last 24 hours.
- One line per Battery on the same chart, with names and distinct colors.
- Existing stored Telemetry contains the required SOC and timestamps.
- Dashboard and History tabs; Dashboard is the default. History has a fixed
  0–100% scale, a rolling 24-hour window in browser-local time, and time/SOC
  details on hover or tap. No date picker or zoom.
- History loads on entry, with no automatic refresh.
- Break lines when the time between readings exceeds the deployment's
  configured `poll_interval_seconds`. The user selected the poll interval;
  the final scope uses it directly, without an added tolerance.
- Show only recorded readings, with no extension to the window edges.
  Show an empty-state message when there are no readings in the window.

## References

- [Current specification](../spec.md)
- [Dashboard behavior](../../../docs/operations/dashboard.md)

## Comments

- 2026-11-01: User confirmed the final scope and requested to-spec synthesis,
  then accepted the browser/app testing seam.

- 2026-11-01: User selected `poll_interval_seconds` for the gap rule.
  Final scope is ready for shared-understanding confirmation; implementation
  has not started.

- 2026-11-01: User accepted navigation/chart recommendations, rejected
  automatic History refresh, and requested gaps based on config.toml's
  deployment-specific interval rather than twice the background interval.

- 2026-11-01: User chose SOC and accepted per-Battery lines. Read-only
  exploration confirmed a vanilla-JavaScript Dashboard with SSE and a history
  API. Default collection intervals are 10 seconds active and 600 seconds
  background; missing reads are not stored. No storage change is required.

- 2026-11-01: Claimed for design grilling. Repository fact exploration is in
  progress. Implementation awaits a confirmed shared understanding.

## Answer

Confirmed and published the [SOC History specification](../../monbat-history/spec.md).
Implementation is tracked in [ticket 30](30-implement-soc-history-tab.md).
The spec covers navigation, static SOC history, strict configured gaps, and
browser/app validation. Cross-checked against existing history and browser-test
boundaries; no application code was changed.
