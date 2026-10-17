# Repository guidance

## Tasks and specifications

Before implementing a ticket, read its file and the relevant sections of
[the spec](.scratch/monbat/spec.md). Use [the map](.scratch/monbat/map.md) to find
tasks and dependencies. Claim a ticket before work; record the result and
validation when resolving it.

For tracker layout, read [issue-tracker.md](docs/agents/issue-tracker.md).
For triage changes, read [triage-labels.md](docs/agents/triage-labels.md): work
lifecycle belongs in `Status`, readiness belongs in `Triage`.

## Domain and operational docs

Before domain changes, read [GLOSSARY.md](GLOSSARY.md) and relevant ADRs as
specified in [domain.md](docs/agents/domain.md).

- Configuration, discovery, or storage setup: [configuration.md](docs/operations/configuration.md).
- Poller scheduling, freshness, Dashboard, or HTTP API: [dashboard.md](docs/operations/dashboard.md).
- BLE parsing or BMS fields: [redodo.md](docs/protocol/redodo.md) and spec section 4.2.

Keep the README focused on quick start and documentation links. Update the
relevant focused doc when behavior changes.

## Agent skills

### Issue tracker

Issues and specs use local Markdown under `.scratch/<feature>/`.
See [issue-tracker.md](docs/agents/issue-tracker.md).

### Triage labels

Use the existing five triage values in `Triage:`; work lifecycle uses `Status:`.
See [triage-labels.md](docs/agents/triage-labels.md).

### Domain docs

Use the single-context layout: root `GLOSSARY.md` and `docs/adr/`.
See [domain.md](docs/agents/domain.md).

### Architecture review

When the user invokes `$mattpocock-skills:improve-codebase-architecture`, use
that skill to find deepening opportunities and present its HTML report.
Use `codebase-design` for design vocabulary, `grilling` to explore the chosen
candidate, and `domain-modeling` to record resolved terms and decisions.
