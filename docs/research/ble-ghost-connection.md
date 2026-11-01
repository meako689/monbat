# Linux BLE reconnect without discovery

Researched 2026-10-19 for Battery `bat-2`, configured address
`AA:BB:CC:00:00:02`. This note separates reconnect mechanisms from proof of a
working radio link. It does not establish that the BMS has a firmware fault.

The user identifies bat-2 as a Redodo 24 V 100 Ah Bluetooth Battery produced
in 2024. Firmware is uncertain: 1.1.0 or 1.0.1. Further remote recovery was
stopped at the user's request. Development implications are recorded in
[ticket 26](../../.scratch/monbat/issues/26-reconnect-with-cached-ble-devices.md).

## Findings

- **A known address can bypass general discovery.** BlueZ exposes experimental
  `Adapter1.ConnectDevice`. Its contract explicitly says no General Discovery
  is needed. It creates or reuses the Device1 object, returns after physical
  connection, and continues service discovery. Set `AddressType` explicitly:
  the default is BR/EDR, not LE. The documented LE values are `public` and
  `random`. [BlueZ Adapter API][adapter]
- **A cached Device1 object can be connected directly.** `Device1.Connect`
  connects its supported profiles; `Disconnect` terminates the low-level ACL
  link even if a profile misbehaves and can cancel a pending Connect call.
  This requires the real object to exist. An invented object path is
  insufficient. [BlueZ Device API][device]
- **BleakClient(address) still scans.** Current Linux backend calls
  `find_device_by_address` when its device path is absent. A supplied BLEDevice
  sets that path and bypasses the scan, but the BlueZ object must still exist.
  Thus the supplied bat-1 `device ... not found` traceback is consistent with
  a cached BLEDevice whose BlueZ object disappeared; it does not show a remote
  BMS connection. [Bleak Linux client source][bleak]
- **Bypassing discovery cannot bypass radio advertising.** The initiating
  Link Layer listens for advertising packets from the selected device and
  answers them to start a new connection. Direct connection may catch
  directed/connectable advertising that normal discovery misses, but cannot
  connect a peripheral that sends no suitable advertising packets.
  [Bluetooth Core v6.1, Vol 6 Part B §1.1 and §4.4.4][core]
- **A real orphaned BLE link should expire.** Both Central and Peripheral use
  the ACL supervision timer, reset by valid received packets. The timeout is
  100 ms–32 s; expiry means connection loss. If the laptop radio was actually
  off for longer than 32 seconds, a standards-compliant BMS cannot still have
  a live link to that laptop. Persistent absence then suggests another central,
  BMS application/firmware state, power/sleep state, address change, or reception
  problems. This is an inference, not a diagnosis.
  [Bluetooth Core v6.1, Vol 6 Part B §4.5.2][core]

## Bounded diagnostic sequence

Keep Monbat stopped. Use the actual adapter path if it is not `hci0`.

```sh
bluetoothctl show
bluetoothctl info AA:BB:CC:00:00:02
busctl --system tree org.bluez
hcitool con
busctl --system introspect org.bluez /org/bluez/hci0 org.bluez.Adapter1
```

The first commands inspect local state; they do not prove the peripheral is
available. `hcitool con` reports kernel/controller connections. Modern
`bluetoothctl connect` first looks for a known Device1 proxy and may offer a
scan when absent; it is not a reliable way to force a missing-object connection.
[BlueZ bluetoothctl source][ctl]

If the target Device1 exists, try its Connect method without running discovery:

```sh
busctl --system --timeout=30 call org.bluez \
  /org/bluez/hci0/dev_AA_BB_CC_FE_00_01 org.bluez.Device1 Connect
```

If `ConnectDevice` is exposed and the public address type is known:

```sh
busctl --system --timeout=30 call org.bluez /org/bluez/hci0 \
  org.bluez.Adapter1 ConnectDevice 'a{sv}' 2 \
  Address s AA:BB:CC:00:00:02 AddressType s public
```

A client-side timeout is not itself evidence that the server-side attempt has
been cancelled. Inspect local state after the attempt and use Device1.Disconnect
when the object exists. On the inspected host, the parent investigator reported
BlueZ 5.64 and no `ConnectDevice` method in introspection, so that route is not
available without changing daemon configuration.

Legacy `gatttool` can attempt an ATT connection to an explicit address/type
without prior general discovery. A bounded, read-only service query is:

```sh
timeout 18s gatttool -b AA:BB:CC:00:00:02 -t public --primary
```

Service discovery is a GATT operation after connection, distinct from BLE
advertising discovery. It does not change battery protection or charge/discharge
settings. In an interactive gatttool process, `disconnect` closes the ATT
channel even while connecting; process exit also closes its file descriptors.
It cannot send a termination packet for an old link that this controller no
longer owns. [BlueZ 5.64 gatttool sources][gatttool] [interactive source][interactive]

`hcitool -i hci0 lecc AA:BB:CC:00:00:02` is a lower-level public-address LE
connection command. `--random` changes the **peer** address type; `--static`
changes the **local** address type. It requests a connection directly and prints
a numeric handle on success. `hcitool -i hci0 ledc HANDLE` disconnects that
handle. These raw commands require controller privileges and can interfere with
BlueZ activity. Their 25-second userspace timeout does not include an explicit
LE Create Connection Cancel in hcitool's implementation, so prefer the D-Bus
or socket routes. [BlueZ hcitool source][hcitool]

If privileged diagnostics become available, capture one controlled attempt
with `btmon` and correlate advertising reports, LE Create Connection/Extended
Create Connection, Connection Complete status, and Disconnect Complete events.
This distinguishes local controller rejection from a connection attempt that
never receives a suitable advertisement. [BlueZ btmon manual][btmon]

## BMS wake or reset evidence

No model-specific Redodo Bluetooth reset/wake procedure was verified during
this research. The official product/manual pages returned
`local_rate_limited`, although the official sitemap identified the manual index
and Smart Bluetooth product page. Do not apply an inferred charging, terminal
shorting, or protection-reset procedure to an unidentified battery model.
Use the exact model's manual or manufacturer support for a physical Bluetooth
module reset. [Redodo manual index][redodo-manual] [Redodo product page][redodo-product]

Follow-up research retrieved the official 24 V 100 Ah simplified manual.
Its activation procedure concerns protection cutoff; no exact-model BLE reset
was verified. See [the Redodo reset research](redodo-bluetooth-reset.md).

## Operational observations

These observations came from the SSH session on 2026-10-19, not the published
sources above:

- Monbat was stopped. Initially `hcitool con` showed only a keyboard, with no
  established bat-2 link.
- A 12-second Bleak scan saw bat-1 at RSSI −78 dBm and did not see bat-2.
- The 18-second direct public-address gatttool attempt for bat-2 timed out
  (`timeout` exit 124). The same read-only query for bat-1 returned its service
  list immediately, including FFE0. This establishes that the direct-query path
  worked for the control battery.
- A later bat-2 attempt showed LE handle 0, state 5 (connecting), not an
  established link. The investigator switched the adapter off before the
  intended 45-second window finished; the attempt ended with software-caused
  connection abort (103). That result is an interrupted attempt, not an
  independent connection timeout.
- `btmon` failed with permission denied and noninteractive sudo was unavailable.
  `bluetoothctl power off` was permitted. A 35-second adapter-off interval,
  followed by adapter-on and a fresh 40-second direct attempt, also timed out
  (`timeout` exit 124). Adapter power was restored. The keyboard reconnected,
  and no bat-2 connection remained in `hcitool con` after the attempt.
- The final 12-second scan again saw bat-1 (RSSI −67 dBm) and no bat-2.
  Monbat remained stopped; no battery settings or production code were changed.

An absent advertisement and a failed direct connection do not establish why
bat-2 is unavailable. The evidence does rule out an established bat-2 link on
the inspected local controller before the attempts.

[adapter]: https://github.com/bluez/bluez/blob/master/doc/org.bluez.Adapter.rst
[device]: https://github.com/bluez/bluez/blob/master/doc/org.bluez.Device.rst
[bleak]: https://github.com/hbldh/bleak/blob/master/bleak/backends/bluezdbus/client.py
[core]: https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core-61/out/en/low-energy-controller/link-layer-specification.html
[ctl]: https://github.com/bluez/bluez/blob/master/client/main.c
[gatttool]: https://github.com/bluez/bluez/blob/5.64/attrib/gatttool.c
[interactive]: https://github.com/bluez/bluez/blob/5.64/attrib/interactive.c
[hcitool]: https://github.com/bluez/bluez/blob/master/tools/hcitool.c
[btmon]: https://github.com/bluez/bluez/blob/master/doc/btmon.rst
[redodo-manual]: https://www.redodopower.com/pages/productmanuals
[redodo-product]: https://www.redodopower.com/products/redodo-12v-100ah-smart-bluetooth-lithium-battery
