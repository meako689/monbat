# Redodo protocol source comparison

Date: 2026-10-17. Research only; no commands sent to hardware.

The implementations agree on the basic status request and most telemetry offsets.
They conflict on capacity and voltage widths, the protection region, and state
semantics. Treat these as reverse-engineered observations, not a manufacturer
specification. Preserve raw unknown fields before assigning physical meanings.

## Pinned sources

| Key | Source | Commit | Evidence |
| --- | --- | --- | --- |
| B | [bmsmon protocol documentation](https://github.com/mkeguy106/bmsmon/blob/4534382d00702e14199e2a2aaab50180cf0878ac/CLAUDE.md#protocol-details), [decoder](https://github.com/mkeguy106/bmsmon/blob/4534382d00702e14199e2a2aaab50180cf0878ac/android/app/src/main/java/dev/joely/bmsmon/ble/BmsProtocol.kt), [tests](https://github.com/mkeguy106/bmsmon/blob/4534382d00702e14199e2a2aaab50180cf0878ac/android/app/src/test/java/dev/joely/bmsmon/BmsProtocolTest.kt) | `4534382d00702e14199e2a2aaab50180cf0878ac` | Redodo captured Idle response; documented official-app HCI observations; synthetic framing tests |
| A | [aiobmsble Redodo decoder](https://github.com/patman15/aiobmsble/blob/2a78c0e0ad9ce018236bd39622bf77c21b20d26f/aiobmsble/bms/redodo_bms.py), [tests](https://github.com/patman15/aiobmsble/blob/2a78c0e0ad9ce018236bd39622bf77c21b20d26f/tests/bms/test_redodo_bms.py) | `2a78c0e0ad9ce018236bd39622bf77c21b20d26f` | Decoder, test frames, synthetic first/last protection-bit checks |
| L | [calledit LiTime implementation](https://github.com/calledit/LiTime_BMS_bluetooth/blob/ce4745aee0318209c4aa8d7b00015434b1f590f0/index.html#L30-L60) | `ce4745aee0318209c4aa8d7b00015434b1f590f0` | LiTime app reverse engineering; field comments with physical interpretations |
| C | [chadj LiTime implementation](https://github.com/chadj/litime-bluetooth-battery/blob/c9bc19bffe1a1436cc395290050eb02ce1e9672a/index.html#L178-L220) | `c9bc19bffe1a1436cc395290050eb02ce1e9672a` | Simple Web Bluetooth telemetry viewer |
| E | [ESP32 parser](https://github.com/mirosieber/Litime_BMS_ESP32/blob/662cda98726508fc39f6eaa77e0964b135e2bda9/src/BMSClient.cpp#L81-L108) | `662cda98726508fc39f6eaa77e0964b135e2bda9` | LiTime parser; raw state strings; minimum-length check |

## Status field evidence

Offsets are from the start of the aligned frame. Multi-byte values are
little-endian. `u` means unsigned, `i` means signed; widths are bits.

| Offset | Field | B / A evidence | Other evidence and limits |
| --- | --- | --- | --- |
| 8 | Voltage | B documents cell sum, u32 /1000 V | L/E call it measured/total voltage; names swapped relative to B |
| 12 | Pack voltage | B/A u16 /1000 V | L/C/E read u32; a capture with zero upper bytes cannot distinguish widths |
| 16–47 | Cells | B/A u16 every 2 bytes, /1000 V, up to 16 slots | L/C/E agree on cell slots; active-cell filtering varies |
| 48 | Current | B/A i32 /1000 A; negative discharge | C/E agree; L converts signed current separately |
| 52 | Cell temperature | B i16, direct °C | A reads up to five 2-byte temperature slots starting at 52; tests include negative temperatures; C/E i16, L corrects signed cell temperature |
| 54 | MOSFET temperature | B i16, direct °C | C/E agree; L parses unsigned, so negative MOSFET readings differ |
| 56–61 | Extra temperatures | A includes slots 3–5, trims persistently zero trailing sensors | B does not expose them; zero is a valid temperature, so this is a sensor-detection heuristic |
| 62 | Remaining capacity | B/A u16 /100 Ah | L/C/E agree |
| 64 | Full/design capacity | B u32 /100 Ah; A u32 integer-divides by 100, calls it design capacity | L/C/E u16 /100 Ah; distinguish physical meaning and width with additional captures, especially above 655.35 Ah |
| 68 | Heater/control field | A u32 converted to bool | L says “heat”, bit 0x80 discharge disabled by app, 0x02 heater error; nonzero does not necessarily mean heating |
| 72 | Balance memory | Not decoded B/A | L/E raw 4 bytes; L says saved balancing-cell information |
| 76 | Protection/problem | B docs 8 bytes, decoder reads u32; A reads u64 | L/E read 4 bytes and separately label offset 80 failure state; these are competing region models |
| 80 | Failure state | Included within A u64 problem region | L extracts last three hex digits of 4 bytes, describes cell/BMS error digits; E reads 3 bytes. Neither is a well-established bit schema |
| 84 | Balancing | A u32 balancer | L/E 32-bit cell bitmap; L says one bit per actively balancing cell. B does not expose it |
| 88 | Battery state | B u16: 0 Idle, 1 Charging, 2 Discharging, 4 Disabled | L says 4 charge disabled, 1 charging, 0 discharging/idle, 2 unknown; E retains 2-byte hex; A does not decode state |
| 90 | SOC | B/A u16 direct percent | L/E agree; C derives SOC from capacities instead |
| 92 | SOH | B/A u32 direct percent | L/E agree |
| 96 | Cycle/discharge count | B/A u32 cycles | L/E call it discharge count; full-cycle vs event semantics unresolved |
| 100 | Discharged-capacity counter | B/A do not expose | L raw u32, E u32 /1000 Ah; unit unresolved |

## State and protection interpretations

“Disabled” matches B exactly, but L's narrower “charge disabled” observation
means the reference set does not establish a universal physical definition.
Do not infer that both MOSFETs are off. B's decoder also maps every unrecognized
state to Idle; Monbat should retain its explicit unknown-state behavior.

B and L agree on low protection masks: `0x04` overcharge, `0x20`
over-discharge, `0x40` charge overcurrent, `0x80` discharge overcurrent,
`0x100`/`0x200` high temperature, `0x400`/`0x800` low temperature,
`0x4000` short circuit. B assigns the paired temperature bits to charge then
discharge; L labels both only high/low temperature. No reviewed physical capture
establishes all these protection meanings. A tests bits 0 and 63 synthetically,
demonstrating preservation of the whole 64-bit region, not physical semantics.

Keep the 76–83 region recoverable. Whether it is one u64 protection field or
u32 protection plus a separate failure field remains unresolved. B's known-mask
decoder drops upper bytes despite its own documentation saying eight bytes.

## Frames and BLE behavior

All sources use service FFE0, notification characteristic FFE1, and command
characteristic FFE2. The status command is
`00 00 04 01 13 55 AA 17`; checksum is the sum of preceding bytes modulo 256.
B/A agree total response length is byte 2 plus 4, e.g. `0x65` gives 105 bytes.
B detects header `00 00 <length> 01 93 55 AA`, realigns leading junk, and tests
assembly through 20-byte fragments. A requires one whole frame per notification
and checks length and checksum. C parses notifications directly; E only requires
at least 104 bytes. Those weaker parsers are not framing references.

B reports official Redodo-app HCI observations: ATT Write Request with response,
persistent simultaneous connections to eight packs, roughly 1.5-second reads
for the viewed pack and slower background reads. Its older CLI notes advise
sequential scans/queries due adapter/cache contention; this is operational
advice, not a protocol prohibition on concurrent connections. B says one client
per battery, so the phone app can exclude another client. Write without response
also works per B; C prefers with response.

## Additional read commands

B documents generic request `00 00 04 01 CMD 55 AA CHECKSUM`, response opcode
`CMD | 0x80`, and read commands `0x10` serial, `0x15` configuration/parameters,
`0x16` firmware, `0x41` SOH/SOC, `0x43` nominal capacity. Only status and firmware
were observed in the reported official-app capture. Do not present response
layouts for 0x15/0x41/0x43 as established: the reviewed sources do not provide them.

For serial 0x10, B says ASCII from absolute offset 8 to checksum; tested units
return all FF, meaning no programmed serial. Firmware 0x16 payload starts at
absolute offset 8: relative offsets 0/2/4 are u16 version components, 6 u16 year,
8/9 u8 month/day, 10 onward two NUL-terminated model/version strings. B distinguishes
BMS application firmware from the Beken BLE-module firmware.

L includes exploratory/control opcodes and incorrect fixed checksum bytes for
some MOSFET commands. These are not additional telemetry reads. No exploration
or control commands were exercised for this research.

## Unresolved validation needs

Hardware evidence is needed to distinguish voltage/capacity widths, cycle and
counter units, the 76–83 field split, state 4 triggers, state 2 semantics across
models, heater/control bits, balancing bitmap behavior, and extra temperature
sensor presence. Current 4S Idle captures support offsets and nominal values;
synthetic frames verify parsing but cannot establish those physical meanings.
