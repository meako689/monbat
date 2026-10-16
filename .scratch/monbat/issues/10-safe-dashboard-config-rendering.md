# 10 Safe Rendering of Dashboard Config Values

Type: task
Status: open
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
