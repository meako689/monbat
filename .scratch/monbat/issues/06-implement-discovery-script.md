# 06 Implement: Discovery Script (`monbat discover`)

Type: task
Status: resolved
Blocked by: 01, 03

## Goal

Implement `monbat discover` — the interactive one-off CLI that scans BLE, lets the user pick batteries by index, assigns friendly aliases, and writes `config.toml`.

All decisions are resolved in [issue 03](03-discovery-cli-and-config-schema.md).

---

## Scope

### Files to create / modify

| Path | Action |
|---|---|
| `src/monbat/discover.py` | **Create** — all discovery logic |
| `src/monbat/__init__.py` | **Modify** — route `monbat discover` subcommand |
| `pyproject.toml` | **Modify** — bump `requires-python` to `>=3.15`, add `bleak` dependency |

### Out of scope

- Poller, BMS driver, DB, Dashboard (separate tasks).
- No test suite in this iteration (throwaway script, run once).

---

## Implementation steps

### Step 1 — Add `bleak` dependency and fix `requires-python`

In `pyproject.toml`:
```toml
requires-python = ">=3.15"
dependencies = ["bleak>=0.22"]
```

Run `uv sync` to regenerate `uv.lock`.

---

### Step 2 — Create `src/monbat/discover.py`

Module layout (top-to-bottom):

```
discover.py
├── _SCAN_SECONDS = 10
├── _FILTER_PREFIXES = ("Redodo", "LiTime", "BMS")
├── _FFE0_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
│
├── _scan() -> list[BLEDevice]          # async: BleakScanner, 10 s
├── _filter(devices) -> list[BLEDevice] # filter by service UUID or name prefix; fallback all
├── _print_table(devices) -> None       # numbered table: #, name, MAC, RSSI
├── _prompt_selections(devices) -> list[BLEDevice]  # input loop: pick indices
├── _prompt_alias(device, idx) -> tuple[str, str]   # name → id slug (bat-<n>)
├── _serialize_config(batteries, *, path) -> str    # pure TOML string builder, no deps
├── _write_config(toml_str, path) -> None           # overwrite prompt if file exists
└── run_discover() -> None              # top-level coroutine wired to CLI
```

#### Key design constraints (from spec §4.1 + issue 03)

- **`asyncio.run(run_discover())`** — bleak is async; `discover.py` is entirely async internally.
- **`BleakScanner.discover(timeout=_SCAN_SECONDS)`** — returns `list[BLEDevice]`.
- **Filtering**: iterate `device.metadata.get("uuids", [])` for `_FFE0_UUID`; OR `device.name.startswith(_FILTER_PREFIXES)`; fallback to all devices.
- **`_print_table`**: plain `print()`, aligned with f-strings. No `rich`, no `tabulate`.
- **`_prompt_selections`**: reads comma-separated indices from `input()`. Validates range; loops on bad input. Returns ordered list.
- **`_prompt_alias`**: `input(f"Name for device {device.name} [{device.address}]: ")`. Strips whitespace, defaults to `f"Battery {idx}"` if empty. Slug: `f"bat-{idx}"`.
- **`_serialize_config`**: builds TOML string via Python string concatenation / f-strings. No `tomli_w` or third-party writer. Produces the exact schema from issue 03.
- **`_write_config`**: if `Path(path).exists()`: print warning, `input("Overwrite? [y/N]: ")`, return early on `n`. Write via `Path.write_text(encoding="utf-8")`.

#### Dataclasses (frozen, slots)

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class _SelectedBattery:
    id: str
    name: str
    mac_address: str
```

Used only internally in `discover.py`; not exported.

---

### Step 3 — Wire into `__init__.py`

```python
import sys
import asyncio

def main() -> None:
    match sys.argv[1:]:
        case ["discover"]:
            from monbat.discover import run_discover
            asyncio.run(run_discover())
        case _:
            print("Usage: monbat discover")
```

Uses `match`/`case` (Python 3.10+, fine for >=3.15 target). Guard clause style — no `else` tree.

---

### Step 4 — Manual smoke-test checklist

After `uv run monbat discover`:

- [ ] Scans for 10 seconds, prints spinner or "Scanning…" line.
- [ ] Shows numbered table of filtered (or all) devices.
- [ ] Accepts comma-separated indices; re-prompts on bad input.
- [ ] Prompts alias per device; empty input defaults to `Battery N`.
- [ ] Prints generated `config.toml` before writing.
- [ ] Writes `config.toml` in CWD.
- [ ] On second run with existing `config.toml`: prompts before overwrite.
- [ ] `tomllib.loads(Path("config.toml").read_text())` parses without error.

---

## Acceptance criteria

1. `uv run monbat discover` scans, prompts, and writes a valid `config.toml` parseable by `tomllib`.
2. Zero third-party TOML writer; zero `rich`/`click`/`typer` deps.
3. All code uses `frozen=True, slots=True` dataclasses, specific types, no `Any`, shallow control flow (guard clauses + early returns).
4. Overwrite guard is present and tested manually.
5. `requires-python = ">=3.15"` and `bleak` in `pyproject.toml`.

## Comments

## Answer

Implemented in:
- `src/monbat/discover.py` — async BLE scan, filter, table, selection, alias prompts, zero-dep TOML serializer, overwrite guard, `run_discover()` coroutine.
- `src/monbat/__init__.py` — routes `["discover"]` via `match`/`case` to `asyncio.run(run_discover())`.
- `pyproject.toml` — `requires-python = ">=3.15"`, `bleak>=0.22`; Python 3.15 pinned via `uv python pin 3.15`.

TOML round-trip validated: `_serialize_config()` output parsed cleanly by `tomllib.loads()` with all field assertions passing.

