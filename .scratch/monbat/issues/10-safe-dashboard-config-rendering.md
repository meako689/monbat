# 10 Safe Rendering of Dashboard Config Values

Type: task
Status: resolved
Priority: low
Triage: ready-for-agent
Blocked by: 09

## Goal

Render battery names and addresses from `config.toml` as text in the Dashboard.
Config values must not create HTML elements, attributes, or executable script.

## Scope

| Path | Action |
|---|---|
| `src/monbat/app.py` | Update — render config-provided values safely |
| `tests/test_app.py` | Update — cover labels containing HTML-sensitive characters |

## Implementation

- Use DOM text nodes or `textContent` for config-derived labels, or apply
  context-appropriate escaping before placing data in HTML.
- Do not interpolate battery names or addresses directly into `innerHTML` or
  executable JavaScript.
- Keep the Dashboard fully offline and dependency-free.

## Acceptance criteria

1. A battery name or address containing `<`, `>`, `&`, quotes, or HTML-looking
   text renders literally in the Dashboard.
2. Config-provided values cannot create elements, event handlers, or executable
   script in a browser.
3. Automated coverage verifies the rendered output for HTML-sensitive labels.

## Comments

- Low-priority follow-up; blocked until ticket 09 establishes the Dashboard.
- 2026-10-17: User requested the remaining Dashboard improvement. Include one
  shared card header and a single update flow with independent failure outcomes.
  Verify labels and failures in a real browser; retain offline production HTML.


## Answer

Battery names and addresses now pass through text escaping in one shared card
header for empty and populated Telemetry views. Removed duplicate header HTML.
Replaced the separate summary update path with one update flow using
`Promise.allSettled`; request/JSON handling is shared by its three callers.
Refresh/latest failures retain cards; summary failures hide bank totals while
successful Battery views update. Subsequent updates recover normally.

Added 11 real-Chromium cases through the rendered Dashboard: literal labels
containing quotes, ampersands, image/script/SVG-looking text in both card
states; HTTP, network, and malformed-JSON failures at each endpoint; retained
cards, hidden totals, exact requests, recovery, and absence of page errors.
Playwright is a development dependency only. Its async interface avoids a
synchronous greenlet crash observed on Python 3.15 beta. Browser setup is
recorded in `docs/operations/dashboard.md`.

Validation: `uv run pytest -m 'not integration' -q` — 96 passed, 2 live-hardware
cases excluded. `git diff --check` passed. Production Dashboard remains offline
and dependency-free; no live BLE was exercised.
