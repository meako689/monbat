# Redodo 24V 100Ah Bluetooth recovery research

Researched 2026-10-19 for a Redodo 24V 100Ah Bluetooth battery reportedly
produced in 2024. The reported firmware is uncertain: `1.1.0` or `1.0.1`.
No more SSH or remote recovery was performed for this research.

**No manufacturer-supported Bluetooth module reset was verified for this
hardware.** The official 24V 100Ah manual documents protection recovery, not
Bluetooth recovery. A battery that supplies normal power but is absent from
Bluetooth discovery does not meet the manual's stated protection-recovery
condition. Obtain the exact model's procedure from Redodo before treating a
charger, long button press, or app shutdown as a Bluetooth reset.

## Official evidence

### Public manual: protection activation only

The official [Product Manuals index][index] says:

> The following is the simplified version of the product manual. A more
> comprehensive product manual will be included in the product box.

Its `24V 100Ah` download links to an eight-page [official Shopify CDN PDF][pdf].
The cover identifies `25.6V 100Ah (100A BMS)`. The manual does not identify a
Bluetooth hardware revision or firmware. The PDF has scanned pages; the relevant
pages were rendered, OCRed, and page 7 visually verified.
The illustrated case is the long `532 × 207 × 215 mm` design (page 2 overview),
with top terminals and no depicted button. This helps distinguish the manual's
hardware from the current compact Group 31 product; it does not prove the user's
battery has the same internals.

Page 7, **“WHAT TO DO WHEN THE BATTERY STOPS WORKING?”**, addresses batteries
that cannot work, cannot charge, or have voltage below 18 V. Its explicit
condition is:

> If the BMS has cut off the battery for protection, follow the below steps
> to activate it.

The documented procedure is:

1. “Cut off all the connections from the battery.”
2. “Leave the battery aside for 30mins.” The text expects recovery to normal
   voltage above 20 V, followed by a full charge.
3. If it does not recover, use **one** of the alternatives: a charger with
   lithium battery activation function to fully charge it, or a controller
   supporting 24V LiFePO4 charging for 3–10 seconds in sunny daytime.

The page 2 overview specifies charge voltage `28.8 ± 0.4 V` and recommended
charge current `20 A`. These are that manual's battery specifications, not a
Bluetooth reset recipe.

**Applicability:** this supports activation after a protection cutoff on the
manual's battery. It does not claim to restart the BLE module, clear a stuck
connection, or factory-reset the BMS. Removing external charging/load connections
also does not establish that an internally powered BLE module loses power.
There is no documented long-press duration or Bluetooth reset button in this
manual.

### Current Bluetooth model and official web pages

The current [24V 100Ah Group 31 Bluetooth product page][product] identifies
model `AE-C14514B-0E`, Bluetooth 5.0, and real-time monitoring through the Redodo
app. It is marketed as a new arrival on the official site. The page offers a
separate `24V 100Ah | No Bluetooth` variant. Its visible FAQ covers trolling
motors, cranking, and replacement of two 12 V lead-acid batteries; it does not
give a Bluetooth reset procedure.

This current model is **not confirmed to match the user's 2024 battery**. The
generic public manual cannot establish compatibility with its BLE module.

The official [battery app download page][app] provides app download/monitoring
information; no reset, wake, disconnect, or sleep procedure was found there.
The official [FAQ page][faq] contains account/order/payment/delivery questions,
not battery Bluetooth troubleshooting. None of these inspected pages established
a factory reset, charger-triggered Bluetooth reboot, or long-button-press
procedure for the 2024 battery.

## Operations that must remain distinct

| Operation | Evidence and limit |
|---|---|
| BLE reconnect or disconnect | Operates on a live radio link. The Linux investigation did not find an established bat-2 link. See [the connection research](ble-ghost-connection.md). |
| Wake after protection cutoff | The official manual's 30-minute isolation/activation procedure above. It concerns battery output and charging availability. |
| Restart Bluetooth module | No exact-model manufacturer procedure verified. External terminal isolation is not proof of internal module power cycling. |
| Factory reset | No documented procedure found in the inspected official sources. It may affect BMS parameters; do not equate it with reconnect. |
| App reset/shutdown | Requires a working connection to send an app command. No official recovery contract was found. It cannot repair a radio that the app cannot connect to merely by selecting an in-app action. |
| Charge/discharge MOSFET switching | Changes battery power paths. It does not establish a BLE reboot. |

The repository's [wire specification](../protocol/redodo-wire-spec.md#state-changing-and-uncertain-commands)
records a community reverse-engineered shutdown command reported to enter deep
sleep and remove BLE power. That is a state-changing command with model-specific
recovery, outside Monbat's read-only scope. The community example is a **12 V
T12100**, not this 24 V battery. Do not use its shutdown or 12 V activation
narrative as a reset procedure here. The same source distinguishes BMS firmware
from Beken Bluetooth module firmware; the user's remembered version does not
identify which component it belongs to. [Pinned community source][community]

## Useful next step

For a Bluetooth-only failure with normal battery output, request the full manual
and the **Bluetooth module restart/wake procedure for the exact 2024 hardware**
from Redodo. The official manual/index list `service@redodopower.com`; the site
also lists `+1 (855) 509-2404`. No message was sent.

Provide the model/serial label, production date, physical button presence,
whether output and charging work, measured terminal voltage, and both firmware
fields if previously recorded. Include the incident evidence: monitor stopped,
no established target link on Linux, normal control battery works through direct
GATT, target absent from scans and direct attempts failed, and adapter off for
more than the BLE supervision timeout did not restore discovery. Ask specifically
whether a supported recovery can preserve BMS parameters and charge/discharge
state.

## Retrieval limits

Direct HTTP requests to the main/regional sites and Shopify `.js`/`.json`
product endpoints returned `local_rate_limited` or failed. Native Microsoft Edge
navigation loaded the official manual index, app page, product page, and FAQ.
The revealed CDN PDF URL downloaded normally. No archived exact 2024 Bluetooth
manual or firmware-specific release notes were verified. The public simplified
manual is incomplete by the manufacturer's own description, so absence of a
procedure in it is not proof that no supported procedure exists.

Follow-up [community research](redodo-community-reset.md) includes firsthand
general BMS recovery reports, including a deeply discharged 24 V Redodo bank.
Those reports broaden the available experiments but do not verify Bluetooth
recovery for this exact hardware.

[index]: https://www.redodopower.com/pages/productmanuals
[pdf]: https://cdn.shopify.com/s/files/1/0561/7641/0714/files/Redodo_24V_100Ah_lithium_battery_product_manual.pdf?v=1715657703
[product]: https://www.redodopower.com/products/redodo-24v-100ah-group-31-bluetooth-lithium-battery
[app]: https://www.redodopower.com/pages/download-app
[faq]: https://www.redodopower.com/pages/faq
[community]: https://github.com/mkeguy106/bmsmon/blob/4534382d00702e14199e2a2aaab50180cf0878ac/CLAUDE.md
