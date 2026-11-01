# Linux deployment

Use [scripts/deploy_linux.py](../../scripts/deploy_linux.py) to deploy an exact
published commit. It defaults to a read-only plan. `--apply` performs the restart.
Database preparation, backup, and rollback configuration are manual.

## Prepare

1. Finish the candidate's required checks and commit its changes. Publish the
   candidate to origin when deployment is authorized. Pin its full commit SHA.
2. Read the ticket's schema contract and [database setup](configuration.md).
   Keep the current database for compatible changes. If a fresh database is
   required, save the original config, stop the service gracefully, make a
   consistent SQLite backup through the backup API, and manually set
   `poller.sqlite_path` to a new persistent absolute path. Preserve the original
   database and its sidecars. Use `--start-stopped` for the subsequent deployment.
3. Preserve a compatible config/database for rollback. Keep config backups and
   SQLite files private and Git-ignored or outside the checkout. Include `-wal`
   and `-shm` sidecars in local exclusions when needed. Ongoing storage and the
   only rollback copy must not live under `/tmp`.
4. Dashboard tabs may stay open during deployment. Note which Batteries were
   available before cutover. The script requires every configured Battery to
   produce a fresh reading before declaring success. Close subscribers only
   when specifically checking background startup/cadence.

The Linux host needs the checkout's existing `.venv` with Python 3.11+, Git,
`uv`, and `screen`. The host's checkout
must be clean, and `config.toml` must be ignored. The SSH repo path must identify
**the running service's working directory**; `~/` paths use the remote home directory, and relative paths resolve from
the SSH login directory. An existing service must be the
single Python Monbat service process in that checkout. Detection supports
both `monbat` and `monbat serve`, with optional `--log-level LEVEL`, including
manual launches. Discovery and unrelated Python processes are excluded.

Load the ignored access file on the controlling computer:

```sh
set -a
source .env.local
set +a
```

It supplies `MONBAT_LINUX_SSH_TARGET` and `MONBAT_LINUX_REPO_PATH`; the Dashboard
URL is also available there. Keep actual host values and credentials local.

## Plan and deploy

From the committed candidate checkout, pin the source once and choose a unique ID:

```sh
deployment_commit="$(git rev-parse HEAD)"
deployment_id="ticket22-20261102"
uv run python scripts/deploy_linux.py \
  --commit "$deployment_commit" --id "$deployment_id"
```

The plan inspects the checkout, ignored config, matching service, tools, and
persistent log location. It prints previous/candidate commits and Battery count.
It does not fetch, signal processes, change source/configuration, or open SQLite.
Candidate availability is verified during execution after fetching origin.

For an authorized deployment, run the same inputs with `--apply`:

```sh
uv run python scripts/deploy_linux.py \
  --commit "$deployment_commit" --id "$deployment_id" --apply
```

Add `--start-stopped` only when the service is already stopped, such as after
manual database preparation or a failed cutover. `--log-level` overrides the
existing level; otherwise the script preserves it, or uses INFO when starting
from a stopped state. `--timeout` bounds each Git/environment or HTTP validation
phase (default 120 seconds); `--stop-timeout` bounds total process shutdown
(default 60), including application/BLE cleanup after the five-second HTTP
grace period. Older deployments without the HTTP timeout may still need their
SSE connections closed during the first upgrade.

The script sends itself over SSH and executes with the checkout's `.venv/bin/python`. It does not depend on the
host's older system Python. Its steps
are fixed:

1. Acquire the checkout deployment lock and reject dirty source, multiple servers,
   missing tools, reused deployment IDs, or temporary log/state storage.
2. Save the previous commit and log level in private state. Fetch origin and
   require the exact candidate to exist on a fetched remote branch.
3. Send SIGINT to the identified server after checking its process start identity.
   Uvicorn gives open HTTP/SSE requests five seconds, then cancels remaining
   requests and runs application/Poller cleanup. Browser tabs reconnect after
   restart. Wait for process exit and port release; the separate shutdown
   deadline still prevents replacement if application cleanup cannot finish.
4. Select the exact commit with `git switch --detach`, then run `uv sync --locked`.
   The deployed checkout deliberately has detached HEAD; the branch tip is not
   the source of deployment identity.
5. Launch one detached `screen` service with persistent timestamped logs.
6. Require HTTP success and a new, fresh reading from every configured Battery,
   then verify the selected revision and single running process.

**The script does not read, back up, create, migrate, or validate a database.**
It reads `config.toml` for service/Battery settings and leaves its bytes unchanged.
The service uses the database configured manually.

Private `state.json`, `commands.log`, and `service.log` are stored on Linux under
`$XDG_DATA_HOME/monbat/deployments/<id>`, or
`~/.local/share/monbat/deployments/<id>` when XDG is unset. The deployment directory
has mode `0700`. These files contain operational details and stay outside Git.

## Failure and rollback

A nonzero exit means the rollout was not accepted. The service may be stopped
or the candidate may still be running. **There is no automatic rollback:** the
script cannot choose a compatible database/configuration on the operator's behalf.

Inspect private state/logs and actual process state first. If environment setup
failed and `.venv/bin/python` is absent, repair the checkout environment with
`uv sync --locked` before invoking the recovery script. Resolve a shutdown
failure before starting another Poller. Recover using the recorded previous
commit and a manually restored compatible configuration/database:

```sh
uv run python scripts/deploy_linux.py \
  --commit "$previous_commit" --id "$rollback_id" --apply --start-stopped
```

Set those inputs from the recorded previous SHA and a new unique rollback ID.
Restore the previous log level explicitly if the candidate used a different one.
If a matching candidate server is still running, this command stops it gracefully
before selecting the old source. Retain candidate logs and any new database for
analysis. Keep new-schema readings separate from historical data during recovery.

## Finish validation and record evidence

The script verifies source/process identity, HTTP, and fresh Battery readings.
It does not prove browser rendering, API field correctness, connection reuse,
long-run stability, or sleep/resume recovery.

After a successful cutover:

- Check ticket-specific latest/history/SSE and persistence contracts manually.
- Open the Dashboard in a real browser; confirm three successive readings per
  available Battery, visible updates, and no rendering errors.
- Close every subscriber. After the grace period, confirm retained clients release
  and active collection stops. Observe the next configured background pass when
  practical; retain cadence and record long-cadence observation as pending if needed.
- If direct access is unreachable, use a bounded SSH tunnel for browser checks,
  close it afterward, and report direct reachability separately.

Publish a sanitized summary under `.scratch/<feature>/validation/`, linked from
the ticket and map. Record revisions, config/database preparation, first readings,
script verdict, manual checks, failures, rollback, and remaining observations.
Keep private identifiers, raw captures, config backups, and unsanitized logs
ignored. Scan staged, unstaged, and untracked artifacts before committing.

References: [ticket 21 evidence](../../.scratch/monbat/validation/21-20261101-deployment.md)
and the [sleep/resume validation plan](../../.scratch/monbat/plans/27-sleep-resume-validation.md).
