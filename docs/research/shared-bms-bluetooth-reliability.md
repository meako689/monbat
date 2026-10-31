# Shared battery BLE family and reliability reports

Researched 2026-10-19. No remote device operations were performed.

**Bluetooth reliability complaints recur across Redodo, LiTime, and PowerQueen.
The reviewed evidence does not establish that the user's precise failure—no
bat-2 advertising after the previous central was switched off—is common, or that
the shared BMS hardware caused it.** Similar-looking connection errors have
different causes. No incident denominator is available, so a failure rate cannot
be inferred from support threads.

## What is actually shared

The [pinned bmsmon protocol notes][bmsmon] identify a Beken `BK-BLE-1.0`
UART-to-BLE bridge family across Redodo, LiTime, PowerQueen and other brands.
They list related device prefixes and service FFE0, notification FFE1, and
command FFE2. Captured Redodo and independently reverse-engineered LiTime
implementations share the status frame and many data offsets; see the
[repository's source comparison](redodo-protocol-sources.md).

This supports a **shared communication family**, not identical complete BMS
boards, settings, power management, or firmware across every branded battery.
The bridge module is separate from the BMS application. A Beken address prefix
identifies an address allocation, not the whole battery's electronics.

In [LiTime support issue 472][change], the maintainer explicitly says:

> LiTime has change their used BMS and it is difficult to distinguish the two types.

The affected owner reported success after installing a detection fix
([confirmation][change-fixed]). This is concrete evidence that even one brand
uses distinguishable BMS variants. Brand/name/protocol resemblance is insufficient
to assign the user's battery the same firmware defect as another unit.

## Reports and symptom matching

| Report | Observation and outcome | Relationship to this incident |
|---|---|---|
| [Redodo aiobmsble issue 305][redodo-error], October 2026 | Owner looping over four Redodo 12V 100Ah devices reported rising D-Bus stream counts and Bleak `manager.add_device_watcher` → `_check_device` → `device ... not found`. | Matches the **bat-1 traceback** closely. It supports recurring host/library lifecycle or stale-object problems. It does not establish permanently silent BMS advertising or the cause of bat-2's absence. |
| [PowerQueen BMS_BLE-HA issue 287][pq] | Owners reported discovery/setup failures. Logs included unavailable proxy connection slots; one owner later confirmed a separate fault was with the Bluetooth proxy and operation resumed. Version changes also affected setup. | Shows recurring integration/transport failures while battery-side hardware defect remains unproven. Host proxy issues are distinct from a battery that remains unadvertised across a fresh local scan. |
| [LiTime IFish owner thread][fish], July–September 2025 | A year-old battery intermittently stopped connecting to a Samsung A70. Another phone could connect; then the original phone worked for a few days before failure recurred. Owner tried app reinstall, phone reboot, full discharge until BMS cutoff, and recharge without lasting success. LiTime eventually offered replacement. | Firsthand recurring Bluetooth usability problem. Crucially, the owner states the battery **appeared in the Bluetooth list during failure**, and the other phone connected. This is not the same as bat-2's absence from advertising. Exact battery model/firmware was not established in the extracted thread text. |
| [Second IFish owner reply][fish] | Another participant says they gave up on Bluetooth “going in & out” and use a shunt. | Additional owner complaint, with insufficient detail to match mechanism, hardware, or absent advertising. |
| [Redodo protected-output reports](redodo-community-reset.md) | Owners reported output lockouts after charging/discharging, temporary isolation recovery, or wake after charger excitation. | BMS protection/output availability is a different symptom. These reports do not demonstrate a stuck live BLE connection. |

### The LiTime case is particularly instructive

The owner reported that the battery would not connect when new until charged,
and later regained connection after charging following winter storage. That
could resemble a module wake issue. However, their later repeatable failure
still showed the battery in the Bluetooth list. Their wife's Apple phone could
connect immediately, enabling the original Android phone to reconnect afterward.

Support suggested complete discharge and recharge to reset the Bluetooth module.
The owner **performed that and reported it did not solve the problem**. Do not
promote that suggestion as a confirmed general reset procedure. The eventual
replacement offer is a reported support outcome, not proof of the underlying
fault or a successful replacement test. [IFish thread][fish]

## Four situations that should not be merged

- **Normal one-client exclusivity:** bmsmon's studied batteries allow one BLE
  client at a time. A connected phone can exclude the monitor. This is expected
  while a real connection exists; it does not explain indefinite silence after
  the central radio is actually off.
- **Host stale BlueZ object or cleanup issue:** a saved BLEDevice path disappears
  from BlueZ, producing `device ... not found`. Independent Redodo reports match
  bat-1's stack. The connection request can fail before a new radio connection
  is attempted.
- **Advertising battery that one app/phone cannot connect to:** the LiTime IFish
  case and some integration issues. These are connection/setup/interoperability
  failures, not demonstrated absence of advertisements.
- **Nonadvertising battery after the central is off:** the current bat-2 evidence.
  The exact cause remains unresolved: module/firmware state, BMS sleep/power
  behavior, another central, changed address, or reception conditions remain
  possibilities. No independent reviewed thread establishes the same enduring
  condition on matching hardware.

A compliant BLE connection loses its supervision timer after at most 32 seconds
without valid peer packets. Thus shared-family anecdotes do not turn the user's
“still thinks connected” hypothesis into proof of a surviving radio link. See
[the Linux connection research](ble-ghost-connection.md) for the Bluetooth Core
source and the actual local controller observations.

## What can reasonably be concluded

The monitor should tolerate missed advertisements, reconnect failures, stale
BlueZ objects, and connection cleanup failures because these are observable
operational conditions in this battery family. That improves recovery when the
peripheral is reachable. It cannot force a genuinely nonadvertising BMS into a
new connection.

To identify a shared firmware defect, the useful comparison is exact BMS model,
BMS firmware, BLE module firmware, independent scan results during failure, and
what reliably restores advertising. Firmware versions belong to separate
components; `1.1.0` or `1.0.1` alone does not identify the module under discussion.
The reviewed reports justify saying **“known recurring connectivity complaints”**,
not **“this exact ghost fault is common across the brands.”**

## Research limits

GitHub API and native Edge forum reading supplied the cited issue/post content.
Targeted searches covered LiTime stuck/disappeared/unconnectable Bluetooth and
PowerQueen connectivity problems. Search-generated summaries were disregarded;
snippets from unread Facebook/Reddit pages were not counted as incident evidence.
Multiple issues from the same owner are not independent incidents. Forums and
support trackers also select for users with problems, so prevalence and causal
hardware attribution remain unknown.

[bmsmon]: https://github.com/mkeguy106/bmsmon/blob/4534382d00702e14199e2a2aaab50180cf0878ac/CLAUDE.md
[change]: https://github.com/patman15/BMS_BLE-HA/issues/472#issuecomment-3254247507
[change-fixed]: https://github.com/patman15/BMS_BLE-HA/issues/472#issuecomment-3267400322
[redodo-error]: https://github.com/patman15/aiobmsble/issues/305#issuecomment-6251510666
[pq]: https://github.com/patman15/BMS_BLE-HA/issues/287#issuecomment-2852647241
[fish]: https://www.ifish.net/threads/litime-bluetooth-connectivity-and-discharging.1718527/
