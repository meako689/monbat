# Research: Python 3.13 and `uv` Environment Compatibility on Linux Mint

- **Ticket**: 01 (`.scratch/monbat/issues/01-python-313-and-uv-environment.md`)
- **Status**: Complete
- **Date**: 2026-10-16
- **Author**: Antigravity Research Agent

---

## 1. Executive Summary & Recommendation

### Recommendation
**Yes, `monbat` can and should upgrade immediately from Python 3.10 to Python 3.13.**

### Summary of Findings
1. **Isolated Standalone Runtime via `uv`**:
   Although Linux Mint 21.3 ("Virginia", based on Ubuntu 22.04 LTS "Jammy") ships with system Python 3.10.12 and lacks Python 3.13 in official apt repositories, `uv` provides built-in Python management (`uv python install 3.13`). It downloads pre-built, isolated CPython binaries from Astral's `python-build-standalone` project. These builds target Linux x86_64 with glibc >= 2.17. The host system has **glibc 2.35**, ensuring full runtime compatibility without touching system packages, adding unstable PPAs, or requiring root privileges.
2. **100% Pre-compiled Binary Wheel Coverage on Python 3.13**:
   All core target libraries (`bleak`, `fastapi`, `uvicorn`, `jinja2`) and their compiled binary C/Rust extensions (`dbus-fast`, `pydantic-core`, `uvloop`, `httptools`, `markupsafe`) have official pre-compiled `manylinux_2_17_x86_64` wheels for Python 3.13 (`cp313`) on PyPI. No local C/Rust compiler toolchain (`gcc`, `cargo`, `rustc`) is required to install or run them.
3. **Bluetooth Stack Alignment**:
   Linux Mint 21.3 ships with **BlueZ 5.64** (`bluetoothctl: 5.64`), which comfortably exceeds Bleak's minimum Linux requirement of BlueZ >= 5.55. On Linux, Bleak communicates with BlueZ over D-Bus via `dbus-fast`, which is fully validated on Python 3.13.
4. **Substantial Codebase Advantages**:
   - **Native `tomllib`**: Included in Python 3.11+ stdlib, eliminating any external TOML dependency for configuration parsing.
   - **`asyncio.TaskGroup`**: Native structured concurrency (PEP 654 exception groups and task groups), providing robust error handling and cancellation for the background BLE `Poller`.
   - **Type Syntax (PEP 695)**: Modern type aliases (`type Alias = ...`) and clean generics without `typing_extensions`.
   - **Diagnostics**: PEP 657 fine-grained traceback annotations with color, speeding up hardware packet parsing debugging.
   - **Support Lifecycle**: Python 3.10 reaches End-of-Life in October 2026, whereas Python 3.13 is supported until October 2029.

---

## 2. Host System Audit (Linux Mint 21.3)

Inspecting the local machine verified the following specifications:

| Component | Host System Value | Requirement for Python 3.13 / Dependencies | Status |
| :--- | :--- | :--- | :--- |
| **OS Distribution** | Linux Mint 21.3 (Virginia) / Ubuntu 22.04 (Jammy) | Linux x86_64 kernel >= 5.15 | Compliant |
| **C Library (glibc)** | Ubuntu GLIBC 2.35-0ubuntu3.15 | `python-build-standalone` >= 2.17; `manylinux_2_17` >= 2.17 | Compliant |
| **Host System Python** | `/usr/bin/python3` (Python 3.10.12) | System Python is kept untouched | Compliant |
| **Apt Package Python 3.13** | Not available in Jammy repos | Bypassed by `uv` standalone Python | Compliant |
| **Bluetooth Subsystem** | BlueZ 5.64 (`/usr/bin/bluetoothctl`) | Bleak requires BlueZ >= 5.55 | Compliant |
| **Build Tools** | No `cargo`, `rustc`, or `pip` in PATH | Pre-built wheels eliminate compilation needs | Compliant |

---

## 3. `uv` Installation & Invocation Analysis

### 3.1 Why `uv` was Missing from PATH
Inspection revealed that `~/.config/uv/uv-receipt.json` was present on the machine:
```json
{
  "binaries": ["uv", "uvx"],
  "install_prefix": "/home/tira/.local/bin",
  "provider": {"source": "cargo-dist", "version": "0.32.0"},
  "source": {"app_name": "uv", "name": "uv", "owner": "astral-sh", "release_type": "github"},
  "version": "0.13.1"
}
```
Furthermore, `~/.profile` already correctly exports `/home/tira/.local/bin:$PATH`. However, `/home/tira/.local/bin/uv` was missing from disk (likely removed during CLI updates or manual directory cleanup).

### 3.2 Installation Method
The canonical, Astral-recommended installation for standalone Linux environments:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
This downloads the official release binary into `/home/tira/.local/bin/uv` and `/home/tira/.local/bin/uvx`.

Verification command:
```bash
uv --version
```
Future updates can be managed with:
```bash
uv self update
```

### 3.3 Python Management via `uv`
Once `uv` is installed, install Python 3.13:
```bash
uv python install 3.13
```
`uv` automatically downloads Astral's `python-build-standalone` release for `x86_64-unknown-linux-gnu` into `~/.local/share/uv/python/cpython-3.13.../`.

When `pyproject.toml` is configured with:
```toml
requires-python = ">=3.13"
```
any invocation of `uv sync` or `uv run` will automatically utilize the managed Python 3.13 binary and bind the virtual environment (`.venv`) to Python 3.13.

### 3.4 Runtime Invocation in `monbat`
- **Development & Testing**:
  ```bash
  uv run monbat discovery   # Run the BLE discovery CLI
  uv run monbat dashboard   # Run the FastAPI server
  uv run pytest             # Run test suite
  ```
- **Direct Virtualenv Execution**:
  ```bash
  .venv/bin/python -m monbat
  ```
- **Systemd User Service (`monbat.service`)**:
  In a headless systemd unit, invoke either via explicit venv python:
  ```ini
  [Service]
  WorkingDirectory=/home/tira/code/monbat
  ExecStart=/home/tira/code/monbat/.venv/bin/python -m monbat
  Restart=on-failure
  ```
  or via `uv`:
  ```ini
  [Service]
  WorkingDirectory=/home/tira/code/monbat
  ExecStart=/home/tira/.local/bin/uv run --frozen monbat
  Restart=on-failure
  ```
  *Recommendation*: Use `/home/tira/code/monbat/.venv/bin/python` in systemd units for zero startup overhead and deterministic process execution.

---

## 4. Target Dependency Compatibility Matrix (Python 3.13 on Linux x86_64)

Every planned dependency was audited against PyPI for Python 3.13 compatibility and binary wheel availability:

| Package | Package Type | Python 3.13 Status | Native Wheels / Extensions | Source / Citation |
| :--- | :--- | :--- | :--- | :--- |
| **`bleak`** (v3.0.2 / v0.22.x) | Pure Python Wheel (`py3-none-any`) | Fully Supported (`requires-python: >=3.10`) | None (pure python package) | [PyPI: bleak](https://pypi.org/project/bleak/) |
| **`dbus-fast`** (v2.24+) | C / Cython Extension | Fully Supported | Pre-compiled `manylinux_2_17_x86_64` wheels for `cp313` | [PyPI: dbus-fast](https://pypi.org/project/dbus-fast/) |
| **`fastapi`** (v0.115+) | Pure Python Wheel (`py3-none-any`) | Fully Supported | None (depends on `pydantic` & `starlette`) | [PyPI: fastapi](https://pypi.org/project/fastapi/) |
| **`pydantic`** & **`pydantic-core`** | Rust Compiled Extension | Fully Supported | Pre-compiled `manylinux_2_17_x86_64` wheels for `cp313` | [PyPI: pydantic-core](https://pypi.org/project/pydantic-core/) |
| **`starlette`** & **`anyio`** | Pure Python Wheel (`py3-none-any`) | Fully Supported | None (pure python packages) | [PyPI: starlette](https://pypi.org/project/starlette/) |
| **`uvicorn`** (v0.32+) | Pure Python Wheel (`py3-none-any`) | Fully Supported | Pure python; optional C accelerators available | [PyPI: uvicorn](https://pypi.org/project/uvicorn/) |
| **`uvloop`** (v0.21+ / v0.23+) | Cython / libuv Extension | Fully Supported | Pre-compiled `manylinux_2_17_x86_64` wheels for `cp313` | [PyPI: uvloop](https://pypi.org/project/uvloop/) |
| **`httptools`** (v0.6.4+) | C Extension | Fully Supported | Pre-compiled `manylinux_2_17_x86_64` wheels for `cp313` | [PyPI: httptools](https://pypi.org/project/httptools/) |
| **`jinja2`** (v3.1+) | Pure Python Wheel (`py3-none-any`) | Fully Supported | Pure python (depends on `markupsafe`) | [PyPI: jinja2](https://pypi.org/project/jinja2/) |
| **`markupsafe`** (v3.0+) | C Speedup Extension | Fully Supported | Pre-compiled `manylinux_2_17_x86_64` wheels for `cp313` | [PyPI: markupsafe](https://pypi.org/project/markupsafe/) |
| **`sqlite3`** | Standard Library | Included in Python 3.13 stdlib | Native SQLite engine | Python 3.13 stdlib |
| **`tomllib`** | Standard Library | Included in Python 3.13 stdlib | Eliminates need for external `tomli` | Python 3.13 stdlib |

### BlueZ & D-Bus Notes
Bleak on Linux communicates directly with BlueZ's system D-Bus interface using `dbus-fast`. Because `dbus-fast` uses pure D-Bus socket protocol serialization over `/run/dbus/system_bus_socket` rather than binding to libbluetooth C headers, no development headers (`libbluetooth-dev`, `libdbus-1-dev`) are required on the host system.

---

## 5. Migration Plan

1. **Re-install `uv`**:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
2. **Update `pyproject.toml`**:
   Update `requires-python` and add target dependencies:
   ```toml
   [project]
   name = "monbat"
   version = "0.1.0"
   description = "Offgrid LiFePO4 battery monitoring service over BLE"
   readme = "README.md"
   requires-python = ">=3.13"
   dependencies = [
       "bleak>=0.22.3",
       "fastapi>=0.115.0",
       "uvicorn[standard]>=0.32.0",
       "jinja2>=3.1.4",
   ]
   ```
3. **Initialize Virtual Environment with Python 3.13**:
   ```bash
   uv sync
   ```
   `uv` will automatically download Python 3.13 standalone build and link `.venv`.

---

## 6. Primary Sources

1. **Python 3.13 Documentation & PEPs**:
   - [What's New In Python 3.13](https://docs.python.org/3/whatsnew/3.13.html)
   - [PEP 719 – Python 3.13 Release Schedule](https://peps.python.org/pep-0719/)
   - [PEP 657 – Include Fine-Grained Error Locations in Tracebacks](https://peps.python.org/pep-0657/)
   - [PEP 654 – Exception Groups and except*](https://peps.python.org/pep-0654/)
   - [PEP 695 – Type Parameter Syntax](https://peps.python.org/pep-0695/)
2. **Astral `uv` and Python Management**:
   - [Astral `uv` Python Installation Guide](https://docs.astral.sh/uv/guides/install-python/)
   - [Astral `python-build-standalone` GitHub Repository](https://github.com/astral-sh/python-build-standalone)
3. **PyPI Package Index & Wheel Metadata**:
   - [Bleak on PyPI](https://pypi.org/project/bleak/)
   - [dbus-fast on PyPI](https://pypi.org/project/dbus-fast/)
   - [FastAPI on PyPI](https://pypi.org/project/fastapi/)
   - [Pydantic-core on PyPI](https://pypi.org/project/pydantic-core/)
   - [Uvicorn on PyPI](https://pypi.org/project/uvicorn/)
   - [uvloop on PyPI](https://pypi.org/project/uvloop/)
   - [httptools on PyPI](https://pypi.org/project/httptools/)
   - [MarkupSafe on PyPI](https://pypi.org/project/markupsafe/)
4. **Linux Mint / BlueZ System Specifications**:
   - Linux Mint 21.3 Release Notes / Ubuntu 22.04 LTS package database.
   - BlueZ 5.64 Release Notes & Bleak Linux Backend Documentation.
