# Local comprehensive Redodo protocol specification

Type: research
Status: resolved

## Scope

Build a cited local wire-protocol specification from the pinned bmsmon
research and reference implementations. Cover BLE transport, framing,
status fields, state/protections, documented commands, captures, conflicts,
and unknowns. Separate upstream claims from Monbat behavior. No hardware
commands or driver changes.

## Validation

Check source pins, field coverage, capture length/checksum, and local links.

## Answer

Created [the local wire specification](../../../docs/protocol/redodo-wire-spec.md)
and [five-source comparison](../../../docs/research/redodo-protocol-sources.md).
Pinned bmsmon, aiobmsble, calledit, chadj, and ESP32 sources. Documented
transport, framing, full known status layout, read/control command distinctions,
serial/firmware payloads, state/protection semantics, captures, disagreements,
and unresolved fields. Linked the implementation overview and qualified the
earlier Disabled research with calledit's charge-disabled observation.

Validation: checked the reproduced capture is 105 bytes, declared length is
101 + 4, checksum is 0x8B, voltage values decode as documented, known protection
mask is 0x4FE4, and all relative links in the four protocol/research documents
resolve. aiobmsble's fetched branch file matched its pinned commit. No driver
changes or hardware requests.
