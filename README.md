# monbat

Local off-grid battery monitoring service for Redodo LiFePO4 batteries over Bluetooth Low Energy (BLE). Linux Mint is the primary deployment target, and macOS is also supported through Bleak. BLE adapter availability and permissions depend on the host operating system.

## Development setup

Install [`uv`](https://docs.astral.sh/uv/) for your platform, then run:

```sh
uv sync
uv run monbat discover
uv run monbat serve
```

`uv sync` creates the project-local `.venv` and provisions a compatible Python runtime. `uv run` runs commands inside that environment without requiring platform-specific activation commands or paths.

`monbat discover` writes `config.toml` in the current directory. Review the
generated battery names and server settings, then run `monbat serve` to start
the Poller and Dashboard. Open <http://localhost:8000> on the same machine.
