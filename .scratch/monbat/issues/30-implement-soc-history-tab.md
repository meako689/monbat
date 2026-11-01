# Implement the SOC History tab

Type: task
Status: open
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

## References

- [Design interview](29-charging-history-tab.md)
- [Project specification](../spec.md)

## Comments

- 2026-11-01: Published from the confirmed design using the to-spec skill.
  The user accepted the existing browser/app test seam. Ready for implementation;
  no application code or deployment changes are part of this specification task.
