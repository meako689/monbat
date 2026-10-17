# monbat

Local, offline monitoring for Redodo LiFePO4 Batteries over Bluetooth Low
Energy. Runs on Linux Mint and macOS. Shows individual Battery Telemetry,
BMS protections, and parallel Battery Bank SOC and net power.

## Quick start

Install [uv](https://docs.astral.sh/uv/), then run:

```sh
uv sync
uv run monbat discover
uv run monbat serve
```

Review the generated `config.toml` before starting the service. Open
<http://localhost:8000>. Bluetooth access requires a compatible adapter and
host permissions.

## Documentation

- [Configuration and database setup](docs/operations/configuration.md)
- [Dashboard and refresh behavior](docs/operations/dashboard.md)
- [BMS protocol and Telemetry](docs/protocol/redodo.md)
- [Specification and tasks](.scratch/monbat/map.md)
