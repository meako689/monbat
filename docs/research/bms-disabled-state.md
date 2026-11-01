# BMS state `4`: naming validation

Date: 2026-10-17

**Keep “Disabled”.** It matches the protocol reference pinned by
[Monbat's Redodo documentation](../protocol/redodo.md). The reference is a
reverse-engineered community implementation, not a manufacturer specification.

## Evidence

- The upstream [README protocol section](https://github.com/mkeguy106/bmsmon/blob/4534382d00702e14199e2a2aaab50180cf0878ac/README.md#protocol)
  directs readers to `CLAUDE.md` for the full protocol documentation and names
  the Android decoder as the protocol reference.
- The [protocol response table](https://github.com/mkeguy106/bmsmon/blob/4534382d00702e14199e2a2aaab50180cf0878ac/CLAUDE.md#protocol-details)
  defines the two-byte unsigned Battery state at offset 88 as
  `0x0000=Idle, 0x0001=Charging, 0x0002=Discharging, 0x0004=Disabled`.
- The [Android decoder](https://github.com/mkeguy106/bmsmon/blob/4534382d00702e14199e2a2aaab50180cf0878ac/android/app/src/main/java/dev/joely/bmsmon/ble/BmsProtocol.kt)
  maps value `4` to `BatteryState.Disabled`.
- The [captured-response test](https://github.com/mkeguy106/bmsmon/blob/4534382d00702e14199e2a2aaab50180cf0878ac/android/app/src/test/java/dev/joely/bmsmon/BmsProtocolTest.kt)
  verifies an Idle capture. It does not establish the physical behavior of
  Disabled through a captured Disabled response.

## Interpretation limits

These sources support the name, but do not define which conditions produce
state `4` or whether it means charging, discharging, or both are blocked.
The command table separately describes charge/discharge MOSFET controls and
shutdown; it does not connect those commands to reported state `4`.
Do not expand the label to “Charging disabled”, “Discharging disabled”,
“Both MOSFETs off”, or “Shutdown” without further evidence.

For explanatory text, use: “BMS reports Disabled (state 4). The protocol
reference does not specify the cause or which power paths are disabled.”

## Broader reference comparison

Later research found a narrower LiTime interpretation in
[calledit's pinned decoder](https://github.com/calledit/LiTime_BMS_bluetooth/blob/ce4745aee0318209c4aa8d7b00015434b1f590f0/index.html#L52):
state `4` is described as “charge disabled.” This qualifies the earlier
finding: Disabled matches bmsmon, but the broader reference set does not
establish a universal physical meaning. See the
[comprehensive source comparison](redodo-protocol-sources.md) and
[local wire specification](../protocol/redodo-wire-spec.md).
