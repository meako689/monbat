# 03 Interactive BLE discovery CLI and TOML configuration schema

Type: grilling
Status: resolved
Blocked by: 01

## Question

What is the exact interactive CLI flow and TOML schema for the Discovery Script to scan for BLE batteries advertising service `0xFFE0`, display detected devices with signal strength (RSSI), prompt the user for human-readable aliases, and persist connection metadata and polling configuration?

## Answer

1. **CLI Invocation**:
   - Integrated as a subcommand: `uv run monbat discover`.

2. **Interactive Flow**:
   - Runs a 10-second `BleakScanner` discovery pass.
   - Filters candidate devices advertising service `0xFFE0` or common battery naming prefixes ("Redodo", "LiTime", "BMS").
   - Falls back to showing all discovered BLE devices if no filtered devices are found.
   - Displays a formatted console table: index, name, MAC address, and RSSI (dBm).
   - Prompts the user to pick batteries by index and assign friendly names (e.g. "Battery 1", "Battery 2"), auto-generating slug IDs (`bat-1`, `bat-2`).

3. **TOML Configuration Schema (`config.toml`)**:
   ```toml
   [poller]
   poll_interval_seconds = 30
   timeout_seconds = 10.0
   sqlite_path = "monbat.db"

   [server]
   host = "0.0.0.0"
   port = 8000

   [[batteries]]
   id = "bat-1"
   name = "Battery 1"
   mac_address = "AA:BB:CC:DD:EE:01"

   [[batteries]]
   id = "bat-2"
   name = "Battery 2"
   mac_address = "AA:BB:CC:DD:EE:02"
   ```

4. **Serialization & Overwrite**:
   - Zero-dependency serialization using a lightweight built-in string template/writer (reads handled by Python stdlib `tomllib`).
   - If `config.toml` already exists, confirms before overwriting.
