# 01 Python 3.13 and uv environment compatibility on Linux Mint

Type: research
Status: resolved
Blocked by: 

## Question

Can `monbat` upgrade from Python 3.10 to Python 3.13 on this Linux Mint system, how should `uv` be installed and invoked, and are the core target dependencies (`bleak`, `fastapi`, `uvicorn`, `jinja2`) fully compatible and installable on Python 3.13 on Linux?

## Answer

Yes, `monbat` will adopt Python 3.15 via `uv`:
1. **Python 3.15 via `uv`**: Python 3.15 is supported natively by Astral's `uv` toolchain via standalone CPython builds running in user space (`~/.local/share/uv/python/`), requiring glibc >= 2.17 which Linux Mint 21.3 (glibc 2.35) satisfies.
2. **`uv` installation and invocation**: `uv` will be installed to `/home/tira/.local/bin` via `curl -LsSf https://astral.sh/uv/install.sh | sh`. Setting `requires-python = ">=3.15"` in `pyproject.toml` enables `uv sync` and `uv run` to provision and manage Python 3.15 automatically.
3. **Core target dependencies**: Core libraries (`bleak`, `fastapi`, `uvicorn`, `jinja2`) and BlueZ 5.64 run cleanly, with native standard library capabilities (`tomllib`, `asyncio.TaskGroup`, and Python 3.15 runtime features).

Detailed research report: [01-python-313-and-uv.md](../../docs/research/01-python-313-and-uv.md).
