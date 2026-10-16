# Python and `uv` environment on Linux and macOS

- **Ticket**: 01 (`.scratch/monbat/issues/01-python-313-and-uv-environment.md`)
- **Status**: Environment setup completed
- **Date**: 2026-10-16

## Recommendation

Use `uv sync` from the repository root to create and update the project-local `.venv`. Run project commands with `uv run`; this avoids shell-specific activation instructions and machine-specific interpreter paths.

Linux Mint remains the primary always-on deployment platform. The application also supports macOS through Bleak's CoreBluetooth backend. BLE operation still requires a compatible adapter and the host OS to grant access.

## Environment setup performed

`uv sync` completed on the current macOS ARM host. It created `.venv`, provisioned CPython 3.15.0b3, and installed Bleak 3.0.2 and pytest 9.1.1, including macOS's PyObjC CoreBluetooth dependencies. Python 3.15.0b3 is a prerelease interpreter selected to satisfy `requires-python = ">=3.15"`; use a final 3.15 release once `uv` makes one available, or lower the project's Python floor if stable Python is required before then.

Useful commands:

```sh
uv sync
uv run monbat discover
uv run pytest
```

Install `uv` using the instructions for the host OS in the [official installation guide](https://docs.astral.sh/uv/getting-started/installation/). Do not copy absolute paths from another machine into project configuration or service examples.

## Platform notes

| Host | Bleak backend | Notes |
| --- | --- | --- |
| Linux Mint | BlueZ | The intended always-on deployment. BLE access depends on BlueZ, D-Bus, adapter availability, and system permissions. Systemd packaging applies only here. |
| macOS | CoreBluetooth | Supported for development and operation. Bleak device identifiers can be UUIDs rather than MAC addresses. |

New configs contain only the canonical `address` key. Readers prefer `address` and fall back to the legacy `mac_address` key, so existing Linux configs remain readable. The stored identifier is returned by Bleak and its format is determined by the operating system.

The discovery CLI and BLE driver use Bleak's cross-platform APIs. The live integration check also probes for an adapter through Bleak instead of invoking the Linux-only `bluetoothctl` command. Environment installation has been confirmed on macOS ARM; live battery polling still needs validation on each target host.

## References

- [Astral `uv` installation guide](https://docs.astral.sh/uv/getting-started/installation/)
- [Astral `uv` Python management](https://docs.astral.sh/uv/guides/install-python/)
- [Bleak documentation](https://bleak.readthedocs.io/)
