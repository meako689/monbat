# Redodo / LiTime BLE wire protocol

Research snapshot: 2026-10-17. All offsets are zero-based from the start of
the realigned response frame, unless a table explicitly says payload-relative.

This is a local specification of a reverse-engineered protocol, not a
manufacturer specification. It covers the Beken BK-BLE-1.0 Battery family
studied by the references. Matching a brand or BLE name does not establish
compatibility with every firmware revision.

## Evidence and scope

Use these source IDs throughout this document:

| ID | Pinned source | Role |
|---|---|---|
| B1 | [bmsmon protocol notes](https://github.com/mkeguy106/bmsmon/blob/4534382d00702e14199e2a2aaab50180cf0878ac/CLAUDE.md#protocol-details) | Protocol tables, commands, field observations |
| B2 | [bmsmon Android decoder](https://github.com/mkeguy106/bmsmon/blob/4534382d00702e14199e2a2aaab50180cf0878ac/android/app/src/main/java/dev/joely/bmsmon/ble/BmsProtocol.kt) | Active parsing and framing behavior |
| B3 | [bmsmon layout](https://github.com/mkeguy106/bmsmon/blob/4534382d00702e14199e2a2aaab50180cf0878ac/android/app/src/main/java/dev/joely/bmsmon/ble/profile/BatteryProfile.kt) | Configurable offsets and limits |
| B4 | [bmsmon captured-response tests](https://github.com/mkeguy106/bmsmon/blob/4534382d00702e14199e2a2aaab50180cf0878ac/android/app/src/test/java/dev/joely/bmsmon/BmsProtocolTest.kt) | One real 12 V/4S capture and synthetic cases |
| A1 | [aiobmsble Redodo decoder](https://github.com/patman15/aiobmsble/blob/2a78c0e0ad9ce018236bd39622bf77c21b20d26f/aiobmsble/bms/redodo_bms.py) | Independent field layout and integrity checks |
| L | [calledit LiTime decoder](https://github.com/calledit/LiTime_BMS_bluetooth/blob/ce4745aee0318209c4aa8d7b00015434b1f590f0/index.html#L30-L60) | App reverse engineering and field comments |
| C | [chadj LiTime viewer](https://github.com/chadj/litime-bluetooth-battery/blob/c9bc19bffe1a1436cc395290050eb02ce1e9672a/index.html#L178-L220) | Additional field decoder |
| E | [LiTime ESP32 decoder](https://github.com/mirosieber/Litime_BMS_ESP32/blob/662cda98726508fc39f6eaa77e0964b135e2bda9/src/BMSClient.cpp#L81-L108) | Additional field decoder and raw state values |

The [source research](../research/redodo-protocol-sources.md) compares further
reference implementations. Agreement between implementations supports an
interpretation; it is not proof that every field was observed changing on
physical hardware. Zero-filled captures cannot establish field width or
meaning by themselves.

## Authority and interpretation rules

The pinned external sources above are the source of truth. Local code,
tests, and earlier implementation tickets cannot establish protocol facts.
For the Redodo baseline, B1 supplies documented wire semantics; B2/B3 and
A1 corroborate field parsing, and B4 supplies capture evidence. Where B1 is
silent, retain externally documented fields with their source attribution.
Where sources conflict, keep the competing interpretations explicit and
require evidence before assigning a universal physical meaning. Do not
choose an interpretation merely because Monbat already implements it.

The wire layout documents externally described regions whether or not an
application stores them. An implementation must preserve unknown bits and
slot identities in fields it exposes, and must not invent physical meanings.
Selecting useful fields for persistence does not change the wire contract.
Client scheduling, storage scope, and derived-value policies belong in the
project specification, not this wire contract.

Current gaps and reimplementation work are tracked in
[tickets 21–25](../../.scratch/monbat/map.md#protocol-reimplementation).

## BLE transport and discovery

Expand a short UUID `xxxx` as `0000xxxx-0000-1000-8000-00805f9b34fb`.

| UUID | Direction from monitoring client | Role | Evidence |
|---|---|---|---|
| `FFE0` | Service | BMS UART-like service | B1, B2, A1 |
| `FFE1` | Notifications into client | Command responses | B1, B2, A1 |
| `FFE2` | Writes from client | Command requests | B1, B2, A1 |
| `2902` | Descriptor write | Enable notifications through the BLE library | B2 |
| `FFE3` | Notify/write | Beken module AT interface; separate from BMS protocol | B1 |
| `180F` | Standard Battery Service | Reported placeholder returning 0% on studied Batteries; do not use for SOC | B1 |
| `f000ffc0-0451-4000-b000-000000000000` | Service | TI OAD firmware update; outside monitoring scope | B1 |

Avoid ambiguous TX/RX names: `FFE1` is received by the monitoring client,
while `FFE2` is transmitted by it.

B1 lists Redodo `R-12*`, `R-24*`, `RO-12*`, `RO-24*`, LiTime `L-12*`,
`L-24*`, `L-51*`, `LT-*`, PowerQueen `P-12*`, `P-24*`, `PQ-*`, and Starry
Sea `S-*`, `SS-*`. A1 additionally requires service `FFE0`, connectability,
and manufacturer ID `0x585A`, and narrows some LiTime patterns by serial
range. These are discovery heuristics, not wire-protocol guarantees.

Subscribe before writing a request. B1 reports both ATT Write Request (with
response) and Write Command (without response) work on the studied module.
Its official-app HCI investigation and Android implementation use Write
Request. An ATT acknowledgement does
not replace the `FFE1` application response.

## Request framing

The documented no-argument command frame is eight bytes [B1, B2]:

```text
00 00 04 01 CMD 55 AA CHECKSUM
```

| Offset | Bytes | Meaning |
|---|---|---|
| 0–1 | `00 00` | Start marker |
| 2 | `04` | Length field; total frame length is this byte + 4 |
| 3 | `01` | Fixed protocol byte in documented frames |
| 4 | command | Operation code |
| 5–6 | `55 AA` | Fixed marker |
| 7 | checksum | Sum of preceding seven bytes modulo 256 |

For this frame form, `checksum = (CMD + 4) & 0xFF`. The status query is
`00 00 04 01 13 55 AA 17`. Do not infer parameterized-write framing from
these no-argument examples.

## Response framing and reassembly

The status response begins `00 00 LEN 01 93 55 AA ...` [B1–B4, A1].
The total frame length is `LEN + 4`; `LEN` is an unsigned byte. The final
byte is the sum of all preceding frame bytes modulo 256 [B4, A1]. This is
an additive checksum, not a polynomial CRC. A response code of `CMD | 0x80`
is documented for status (`93`), serial (`90`), and firmware (`96`) [B1].
Treat that relationship as documented for those commands rather than a
guarantee about every unknown opcode.

| Offset | Meaning |
|---|---|
| 0–1 | `00 00` start marker |
| 2 | Length byte |
| 3 | `01` |
| 4 | Response code |
| 5–6 | `55 AA` |
| 7 | Unassigned byte; zero in the cited status capture |
| 8 onward | Command-specific fields |
| `LEN + 3` | Checksum |

BLE notification boundaries are not necessarily frame boundaries. B2
accumulates fragments, finds the status marker `01 93 55 AA`, and realigns
past stale prefix bytes. A1's handler expects a complete frame per callback;
this is an implementation assumption, not evidence that fragmentation cannot
occur.

A status reader must collect a complete declared response, realign past
stale prefix bytes, validate identity and checksum, and check that every
field it decodes ends before the checksum [B2, B4, A1]. B2 uses a 512-byte
assembly cap. That cap is an implementation safeguard, not a wire length.
The cited full status capture is 105 bytes and includes fields through 103.
A shorter valid frame cannot supply absent trailing fields; mark them
unavailable rather than reading checksum bytes as data. Do not use fixed
66- or 100-byte notification thresholds as proof of completion.

There is no documented sequence number or correlation field. Serialize
requests on each connection to avoid ambiguous replies.

## Status response `0x13`

All numeric fields below are little-endian. `u16`, `u32`, and `u64` denote
unsigned integers of that width; `i16` and `i32` are signed two's-complement.
Ranges list every byte through the field's end.

| Offset / range | Type | Meaning and conversion | Evidence / qualification |
|---|---|---|---|
| 8–11 | u32 | Cell sum voltage, raw / 1000 V | B1 |
| 12–13 | u16 | Pack voltage, raw / 1000 V | B1–B3, A1 |
| 14–15 | disputed | Upper voltage word in L/C/E's u32 at 12 | B1/B2/A1 use u16 at 12; not assigned separately |
| 16–47 | 16 × u16 | Cell slots, each raw / 1000 V | B1–B3, A1; unused zero slots occur |
| 48–51 | i32 | Current, raw / 1000 A; negative discharge, positive charge | B1, B2, A1 |
| 52–53 | i16 | Cell temperature, direct °C | B1, B2 |
| 54–55 | i16 | MOSFET/BMS internal temperature, direct °C | B1, B2 |
| 56–61 | 3 × 2-byte slots | Additional temperature positions in A1's five-slot array starting at 52 | A1; sensor identities and universal presence unestablished |
| 62–63 | u16 | Remaining capacity, raw / 100 Ah | B1, B2, A1 |
| 64–67 | u32 | Full charge capacity, raw / 100 Ah | B1, B2; A1 calls it design capacity and floors to whole Ah |
| 68–71 | u32 | Heater/control region; A1 converts nonzero to true | L supplies control/error-bit interpretations; see conflicts |
| 72–75 | raw 4 bytes | Saved balancing-cell information according to L | L/E; not decoded by B2/A1; exact semantics unresolved |
| 76–83 | u64 region | Protection/problem flags | B1, A1; B2 decode only low u32 at 76–79 |
| 84–87 | u32 | Balancer indication/mask | A1; L/E treat it as a cell bitmap; L says one bit per actively balancing cell |
| 88–89 | u16 | BMS state | B1, B2; see state table |
| 90–91 | u16 | Reported SOC, direct % | B1, B2, A1 |
| 92–95 | u32 | Reported SOH, direct % | B1, B2, A1 |
| 96–99 | u32 | Cycle count | B1, B2, A1 |
| 100–103, if present before checksum | u32 candidate | Discharged-capacity counter | L raw u32, E divides by 1000 Ah; unit/meaning unvalidated |
| 104 through checksum − 1, if present | unknown | Additional trailing bytes | No layout established |
| final byte | u8 | Additive checksum | B4, A1 |

B2 filters converted cell voltages below or equal to 0.1 V; other
references filter unused zero slots. No transmitted cell-count field is
established. Preserve all 16 slot positions before filtering for display.
An empty slot must not renumber later cells. The layout accommodates 4S and
8S Batteries; each reference capture validates only its own series count.

### Conflicting field interpretations

The Redodo baseline follows B1/B2/A1 for core widths. Other decoders
disagree [L, C, E]:

- Offset 8 is named measured/total voltage by L/E, versus cell sum in B1.
  Offset 12 is read as u32 by L/C/E versus u16 by B2/A1. Zero upper bytes
  cannot distinguish the width; the field names are not interchangeable.
- Offset 64 is u16 in L/C/E versus u32 in B2/A1. High-word values or
  capacity above 655.35 Ah would distinguish those layouts. None of this
  establishes whether the capacity is learned full capacity or design capacity.
- Offset 68 is called heat by L, with `0x80` described as discharge disabled
  by the app and `0x02` as heater error. A1's nonzero-to-boolean conversion
  therefore does not establish that a Battery is actively heating.
- Offset 80 is treated as a separate failure field by L/E, while A1 includes
  it in a u64 problem mask. L describes error digits and E reads three bytes;
  neither establishes a complete failure-bit schema.
- A1 reads five temperature slots and uses persistently zero trailing slots
  to infer sensor count. Zero °C is a valid reading, so this is a heuristic.
  L handles MOSFET temperature as unsigned, unlike B2 and C/E.
- L/E call offset 96 a discharge count. Whether it counts full cycles or
  discharge events is unresolved. Offset 100's counter unit is also unresolved.

Use the externally supported Redodo baseline for core layout, but
retain these conflicts when comparing passive captures from other firmware.

### BMS state

| Raw value | Name | Evidence |
|---|---|---|
| `0x0000` | Idle | B1, B4 |
| `0x0001` | Charging | B1, B2 |
| `0x0002` | Discharging | B1, B2 |
| `0x0004` | Disabled | B1, B2 |
| Other | Unspecified; preserve raw value | B1 enumerates only four values; B2 falls back to Idle without defining other states |

Keep “Disabled”: it is the referenced name. No cited Disabled hardware
capture establishes its cause or whether charging, discharging, or both
are blocked. Do not equate it with shutdown, BLE disconnection, or a specific
MOSFET setting. The numerical powers of two alone do not establish that this
field should be decoded as a combinable bitmask.

L supplies a narrower, conflicting LiTime interpretation: `4` is “charge
disabled,” `1` charging, `0` discharging/idle, and `2` unknown. This is useful
evidence for that implementation's studied Batteries, not a universal state
definition. The Redodo baseline label remains Disabled [B1]; the narrower
LiTime claim requires model-specific evidence. See the [source comparison](../research/redodo-protocol-sources.md).

### Protection flags

B1/B2 establish these masks in the low 32 bits:

| Mask | BMS-reported active protection |
|---|---|
| `0x00000004` | Overcharge |
| `0x00000020` | Over-discharge |
| `0x00000040` | Charging overcurrent |
| `0x00000080` | Discharging overcurrent |
| `0x00000100` | High temperature while charging |
| `0x00000200` | High temperature while discharging |
| `0x00000400` | Low temperature while charging |
| `0x00000800` | Low temperature while discharging |
| `0x00004000` | Short circuit |

Test each mask with bitwise AND; multiple protections can be active.
Known masks together form `0x00004FE4`. Retain unknown bits rather than
claiming they are safe or reserved. B1 describes eight bytes and A1 reads
eight, but B2 only reads four. Preserve all eight bytes when exposing this problem/failure region;
zero low bits do not establish that the full eight-byte region is zero.
No labels for the upper 32 bits are established here.

These flags report BMS conditions. Communication failures, stale readings,
and application voltage/temperature thresholds are separate concepts.
Synthetic flag tests verify decoding, not physical protection activation.

### Wire values versus client calculations

Power, capacity-derived SOC, timestamps, freshness, and unavailable-value
policies are client calculations rather than additional fields. B2 displays
power magnitude using absolute current. Keep the signed wire current so a
client can compute signed power. SOC/SOH are documented percentages [B1];
application range checks do not establish manufacturer sentinel values.
Do not assign `0xFFFF` or `0xFFFFFFFF` universal sentinel meanings without
external evidence.

## Other documented commands

The commands below use the eight-byte request form. Classification and names
come from B1/B2. Response coverage is listed explicitly.

| CMD | Request checksum | Reported role | Response evidence |
|---|---|---|---|
| `0x10` | `0x14` | Read serial number | Serial layout below |
| `0x13` | `0x17` | Read status | Status layout above |
| `0x15` | `0x19` | Read configuration/parameters | Response layout not established here |
| `0x16` | `0x1A` | Read firmware version | Layout below |
| `0x41` | `0x45` | Read SOH/SOC | Response layout not established here |
| `0x43` | `0x47` | Read nominal capacity | Response layout not established here |

B2 permits these through a read-command enum, but its write safety predicate
accepts only the exact canonical `0x13` status request. Documenting a command
does not establish response layouts that are absent from the external evidence.

### Serial response `0x10`

B1 documents header `00 00 LEN 01 90 55 AA ...` and ASCII serial data from
frame offset 8 up to the checksum. Studied R-12100 Batteries returned all
`FF` in that region, interpreted as no programmed serial. The advertised
BLE name is not that serial field. No fixed serial length is established.

### Firmware response `0x16`

B1 documents header `00 00 LEN 01 96 55 AA ...`. The following offsets are
**relative to frame offset 8**, unlike the status table:

| Payload offset | Type | Meaning |
|---|---|---|
| 0–5 | 3 × u16 | Major, minor, patch |
| 6–7 | u16 | Build year |
| 8 | u8 | Build month |
| 9 | u8 | Build day |
| 10 onward | NUL-terminated ASCII strings | Hardware and firmware model/version strings |

B1's example is model `T12100`, hardware `V1.2`, BMS firmware `V1.4`, built
2024-03-31. It distinguishes this from the Beken BLE module firmware
(`BK-BLE-1.0`, example `6.1.2`). String lengths and all firmware variants
remain unspecified.

### State-changing and uncertain commands

These descriptions are retained for protocol completeness [B1]. They are
outside Monbat's read-only scope and must not be added to a probing loop.

| CMD | Upstream description | Qualification |
|---|---|---|
| `0x0A` | Enable charging MOSFET | Changes power control |
| `0x0B` | Disable charging MOSFET | Changes power control |
| `0x0C` | Enable discharge MOSFET | Changes power control |
| `0x0D` | Disable discharge MOSFET | Can disconnect the load |
| `0x60` | Shutdown | B1 reports deep sleep and loss of BLE power |
| `0x01` | Product registration | B1's command table assigns a name, but its safety section calls effects unknown |
| `0x02` | Disconnect registration | Same conflict; not a validated read command |

Acknowledgement formats, resulting status values, and recovery behavior across
models are not specified here. B1's recovery narrative is model-specific;
it does not establish a universal reset procedure. All remaining opcodes
have unestablished effects in this spec.

## Connection behavior versus scheduling policy

B1's official-app HCI investigation reports eight retained connections on a
Pixel 6, ATT Write Request, status/firmware reads, and about 1.5-second reads
for the actively viewed Battery. It also documents transient establishment
failures and retry spacing. These are observed client/platform behaviors,
not mandated timing values or universal connection limits.

B1's older CLI advice to query sequentially addresses scan/cache contention.
Its later Android investigation supports retained simultaneous connections.
Do not collapse those into a protocol prohibition on concurrency. Each
Battery connection should still serialize its own requests. B1 reports one
client per Battery; a phone app may prevent another client connecting.

## Captured status fixture

B4 attributes this response to `R-12100BNNA70-A02402`, a 12 V/4S Battery:

```text
000065019355aa007c3300000c340000030d030d030d030d00000000000000000000000000000000000000000000000000000000170018000000000000001027102700000000000000000000000000000000000000000000000063006400000000000000000000008b
```

Verified locally: 105 bytes; `LEN = 0x65 = 101`; checksum `0x8B` equals
the sum of bytes 0–103 modulo 256. Decoded values are pack voltage 13.324 V,
four cells at 3.331 V, current 0 A, temperatures 23/24 °C, remaining/full
capacity 100/100 Ah, Idle state, SOC 99%, SOH 100%, and cycle count 0.
The cell-sum field is 13.180 V, different from both pack voltage and the
sum of the four displayed cell voltages. Do not assume it is interchangeable
with pack voltage or recompute another field from it.

This fixture validates the framing/checksum and these particular values.
It does not validate Disabled semantics, negative temperatures, high-word
capacity/flags, heater activation, balancing, or other command responses.
Synthetic tests remain distinct from hardware observations.

## Remaining questions

- Exact semantics of status byte 7 and any additional trailing bytes.
- Voltage width at 12 and the names/relationship of voltage fields 8 and 12.
- Whether bytes 80–83 are upper protection bits or a separate failure field.
- Physical conditions that produce Disabled and any combined state values.
- Heater/control and balancing-memory behavior across firmware; physical
  validation of L's active-cell bitmap at 84 and error/control bits at 68.
- Presence, ordering, and signedness confirmation of all five temperature slots.
- Whether offset 64 denotes learned full capacity, design capacity, or a
  firmware-specific capacity; references use different names.
- Validated payloads for `0x15`, `0x41`, and `0x43` and acknowledgement formats
  for state-changing commands.
- Universal sentinel values, field ranges, and alternate frame lengths.

Resolve these with cited source changes or passive captures from supported
read commands. Keep unknown bytes and raw values in research evidence.
