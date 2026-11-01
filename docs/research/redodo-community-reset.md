# Redodo community BMS reset and recovery reports

Researched 2026-10-19. Scope includes general BMS recovery, not just Bluetooth
module reset. Sources below are owner posts, reported support instructions, and
reverse-engineering notes. They establish what was reported, not a universal
procedure for the user's Redodo 24V 100Ah Bluetooth battery produced in 2024.

**The best supported noninvasive experiments are full external isolation for
30 minutes, then a proper 24V LiFePO4 charger with activation/wake support.**
Redodo owners report these kinds of recovery for protected outputs. No verified
owner report showed that either restored Bluetooth on the exact 2024 24V 100Ah
model. The isolation step can still be tried as a general recovery experiment;
success means the original fault clears, not that the internals necessarily
power-cycled.

## Firsthand reports

| Source and model | Reported method | Reported outcome and confidence |
|---|---|---|
| [CleanLivin, November 2023][isolation]: four **12V 100Ah Mini SMART**, parallel, explicitly **no Bluetooth** | Quotes Redodo support: discharge into a load above 2 A for 2 minutes, disconnect all connections, wait 30 minutes; voltage should recover to about 13.33 V. | Owner describes identifying and resetting locked batteries repeatedly, three times in six weeks. Eventually returned them. Useful firsthand evidence for temporary output recovery; not a permanent cure or a 24V/Bluetooth result. |
| [24V bank owner, January and May 2025][wake]: **24V 600Ah bank of three Redodo batteries**, explicitly eight-cell batteries, operating about two years | A charger applied to the protected pack restored its output. Their normal AmpereTime 29.2V 20A charger showed fault/protection, and reversing connection order did not help. An old trickle charger did. | January post reports output rose from about 2.27 V to 23 V, lighting worked, SCC powered up and charged. May follow-up reports another wake with an old non-smart charger after repeated deep discharge. Actual 24V recovery, but bank capacity is consistent with 200Ah batteries, not the user's 100Ah model; Bluetooth not mentioned. |
| [Redodo 12V 100Ah owner, July–August 2023][failed] | Tried multiple charging and jump-start approaches on a pack that would not charge or discharge. | Attempts failed; Redodo replaced the battery after support exchanges. This is evidence that charging tricks are not guaranteed to recover every fault. |
| [Redodo 50Ah 12V owner, April 2026][apps] | OEM Redodo app connected; BAT-BMS and Overkill Solar did not. | No reset result. A reply identifies BMS protocol compatibility as the issue. Absence from one app does not prove absent BLE advertising; this differs from the Linux incident. |

### Exact observations behind the 24V recovery

In the [January success post][wake-success], the owner says:

> Disconnected the trickle charger, turned 12V light on, everything works.
> Closed switch between SCC and battery, SCC powers up.
> Closed switch between SCC and pv, SCC charges

The owner had used a **12V charger on the 24V protected pack**. That is a report
of an outcome, **not a recommended charging procedure**. It apparently supplied
enough excitation to release protection; it could not correctly charge a 24V
LiFePO4 pack. Use the appropriate 24V LiFePO4 activation charger, following its
instructions. Do not substitute mismatched chargers, raw panels, lead-acid jump
sources, or unregulated supplies based on forum anecdotes.

The symptoms also matter: this bank was apparently dead after excessive
discharge, with very low voltage at the external terminals. The post does not
show that Bluetooth had failed while output remained normal. Its recovered
external voltage is evidence of BMS output recovery, not cell voltage restoration
from 2.27 V per pack or a demonstrated MCU reboot.

## Internal hard reset: a plausible mechanism, no exact-model success found

The pinned [bmsmon community protocol notes][bmsmon] discuss BMS deep shutdown
and suggest removing/reconnecting the BMS balance/sense connector as a hard
reset. The parent investigator checked that this is a recommendation, not an
explicitly verified successful recovery report. Its hardware example is the
12V `T12100`, not the user's 24V battery.

This requires opening the case and touching wiring connected directly to cells.
It can damage the enclosure/seal, expose high fault current, and damage a BMS if
its supply/sense connections are sequenced incorrectly. No service connector
layout, disconnect order, wait duration, or reassembly procedure for the user's
hardware was found. Thus no internal step-by-step procedure is supported here.
An exact-model service procedure or someone qualified to repair battery packs
is needed before attempting this route.

There is also no confirmed Redodo button-reset procedure in the inspected
reports. In the [Redodo beeping thread][beeping], a commenter mentions a wake
button on **their ANT BMS**, while the Redodo owner later discovers the beep
was from a Fluke multimeter. This is not Redodo wake-button evidence.

## Practical order for this incident

1. Keep all monitors and phone battery apps disconnected. Isolate the suspect
   battery from **all** external connections, including other parallel
   batteries, loads, and chargers, for 30 minutes. Use the installation's safe
   shutdown/disconnection procedure; switching off only the laptop does not
   isolate the battery. This is a reversible general-recovery experiment with
   manufacturer and owner precedent. It may not restart an internally powered
   Bluetooth module.
2. Check whether the original fault cleared, including whether the BMS advertises
   again. If still unavailable, an appropriate **24V LiFePO4 charger with
   activation/wake support** offers a second noninvasive BMS wake experiment.
   Follow that charger's instructions and the battery's charging limits. No
   minimum time guaranteeing Bluetooth recovery was established.
3. If these fail, distinguish normal output/charging from a pack that remains
   protected. A hardware/BMS restart may then require manufacturer service or
   an exact-model internal procedure. The available anecdotes do not establish
   that opening the user's battery is necessary or that a balance-plug reset
   would fix its fault.

The official 24V 100Ah manual separately supports 30-minute isolation and
activation charging **when BMS protection has cut off output**. See
[official-source research](redodo-bluetooth-reset.md) for its exact condition,
page 7 instructions, and charging specifications. The experiments above extend
the investigation to general BMS recovery as requested; Bluetooth success is
uncertain.

## Search coverage and limits

Read DIY Solar threads about locked Redodo Smart Minis, drained 24V Redodo bank,
12V charge/discharge failure, Redodo app discovery, beeping, and budget smart
battery cycling. Search results also identified [GitHub issue 78][github], a
2024 Redodo `R-24100BNN160` integration report with successful telemetry, but it
contains no reset recovery. The [budget-smart cycling thread][cycling] includes
app-toggle suggestions and owner reports that toggling repeatedly failed; much
of it concerns LiTime/WattCycle, so it was not treated as Redodo proof.

Native Google/Edge loaded forum pages while direct forum HTTP requests returned
403. Reddit's `Lithium Standby madness` page was blocked by network security;
its search snippet was not used as a confirmed recovery result. Search-generated
AI summaries were disregarded. No exact 2024 24V 100Ah Bluetooth successful reset
report was verified.

[isolation]: https://diysolarforum.com/threads/bms-battery-one-that-must-reset-by-itself.72618/post-921156
[wake]: https://diysolarforum.com/threads/bad-start-into-2025-drained-redodo-battery-bank.97194/
[wake-success]: https://diysolarforum.com/threads/bad-start-into-2025-drained-redodo-battery-bank.97194/post-1309458
[failed]: https://diysolarforum.com/threads/redodo-12v-100ah-acting-weird-wont-charge-discharge.65471/
[apps]: https://diysolarforum.com/threads/redodo-battery-not-found-in-bat-bms-or-overkill-solar-apps.124079/post-1800840
[bmsmon]: https://github.com/mkeguy106/bmsmon/blob/4534382d00702e14199e2a2aaab50180cf0878ac/CLAUDE.md
[beeping]: https://diysolarforum.com/threads/redodo-battery-beeping.102364/
[github]: https://github.com/patman15/BMS_BLE-HA/issues/78
[cycling]: https://diysolarforum.com/threads/budget-smart-12v-batteries-all-have-the-same-cycling-issue.111783/page-8
