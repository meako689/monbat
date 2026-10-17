# 12 Parallel Battery Bank SOC and net power summary

Type: task
Status: resolved
Triage: ready-for-agent
Blocked by: 11, 13

## Goal

Add a Dashboard section above the Battery cards showing Battery Bank SOC with
a charge bar and one net charging/discharging value in watts.

## Scope

- `src/monbat/app.py`: typed summary view, `GET /api/summary`, and summary UI.
- `README.md`: describe the parallel-only summary and unavailable state.

Use [spec section 4.6](../spec.md#46-parallel-battery-bank-summary) as the
behavior contract. Ticket 11 supplies freshness; ticket 13 supplies corrected
capacity and BMS-reported SOC.

## Acceptance criteria

1. Aggregate every configured Battery as a parallel Battery Bank with the
   same nominal voltage. The section appears above individual Battery cards.
2. Calculate `sum(soc_percent * capacity_ah) / sum(capacity_ah)` from each
   Battery's effective SOC and full charge capacity. Calculate net power as
   `sum(power_w)`; round only for display.
3. Show one SOC percentage and bar, and one net power value: positive means
   charging, negative means discharging, zero means idle. Preserve the sign
   and show a readable state label.
4. When any configured Battery is missing or older than `freshness_seconds`,
   return unavailable totals and render neither a numeric total nor a filled
   charge bar. Explain that fresh readings from all Batteries are required.
   Retain individual cards and their last readings.
5. Nonpositive capacity makes aggregate SOC unavailable; show the unavailable
   summary rather than inventing a weight or dividing by zero.
6. `GET /api/summary` returns `available`, nullable `soc_percent` and `power_w`,
   and a nullable reason (`missing-reading`, `stale-reading`, or
   `invalid-capacity`). On unavailability both numeric fields are null.
7. Preserve the existing dictionary contract of `/api/latest`. Fetch the
   summary on page load and every 30-second update; do not create another BLE
   refresh timer or Poller. Handle summary request failures as unavailable.
8. Keep the UI offline, responsive, accessible, and dependency-free. Render
   labels through text nodes or safe escaping, consistent with ticket 10.

## Validation for implementation

Cover unequal capacities and opposite power signs, zero net power, every
unavailable reason, exact freshness boundaries, and recovery to complete
fresh readings. Example: 100 Ah at 80% plus 200 Ah at 20% gives 40% SOC;
+100 W plus -300 W gives -200 W (discharging).

## Comments

- 2026-10-17: User confirmed parallel only, one net value, hiding totals for
  stale/offline Batteries, and capacity-weighted BMS SOC with capacity-derived
  SOC used only as a fallback by the driver.


## Answer

Implemented typed `BatteryBankSummary` and `GET /api/summary`, using every
configured Battery's effective SOC and full charge capacity as weights, and
summing signed watts. Missing readings, stale readings, then invalid capacity
make both totals null. Freshness uses the shared configurable setting.

The Dashboard renders the summary above Battery cards with an accessible SOC
bar and one signed Charging/Discharging/Idle power value. Unavailable data and
summary fetch failures remove numeric totals and the bar while individual
cards remain. Summary requests use the existing 30-second timer and create no
additional BLE pass. README documents parallel-only operation.

Validation: `uv run pytest -m 'not integration'` — 84 passed, 2 live cases
excluded. Added coverage for weighted SOC, opposite/zero power, unavailable
reasons and precedence, exact freshness boundary, recovery, latest API contract,
section order, and the single timer. `git diff --check` passed. Browser rendering
and live hardware were not exercised.
