# 01 Python and uv environment on Linux and macOS

Type: research
Status: resolved
Blocked by: 

## Question

How should `uv` provision the project's Python environment, and can the current BLE application run on the Linux Mint deployment host and macOS development hosts?

## Answer

The project uses Python 3.15 managed by `uv`, with Linux Mint as its primary deployment target and macOS supported for development and operation.

1. **Environment setup**: Run `uv sync` from the repository root. It creates `.venv`, selects a compatible CPython, and installs dependencies for the current OS and architecture. On the macOS ARM host used for this setup, it installed CPython 3.15.0b3, Bleak 3.0.2, and pytest 9.1.1.
2. **Platform support**: Bleak uses BlueZ on Linux and CoreBluetooth on macOS. Package installation is platform-aware; the lockfile contains OS-specific optional backend dependencies. New configs use Bleak's device identifier as `address`; readers accept the legacy `mac_address` key for existing configs.
3. **Run commands**: Use `uv run monbat discover` and `uv run pytest` so commands use the project environment without hardcoded interpreter or home-directory paths.
4. **Limit**: Environment installation was confirmed on macOS ARM. Linux Mint remains the intended always-on host; live BLE hardware operation depends on adapter access and OS permissions and is not validated by dependency installation alone.

Environment and platform notes: [01-python-313-and-uv.md](../../docs/research/01-python-313-and-uv.md).
