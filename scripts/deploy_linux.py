#!/usr/bin/env python3
"""Deploy an exact commit over SSH. Database preparation is manual."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import fcntl
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import tomllib
import urllib.request


class DeploymentError(RuntimeError):
    pass


def command(*argv: str, cwd: Path, log: Path | None = None, timeout: float = 120) -> str:
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if log is not None:
        with log.open('a') as out:
            out.write(shlex.join(argv) + '\n' + result.stdout + result.stderr)
    if result.returncode:
        raise DeploymentError(f'{Path(argv[0]).name} failed; inspect private command log')
    return result.stdout.strip()


def start_ticks(pid: int) -> str | None:
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


@dataclass(frozen=True)
class Server:
    pid: int
    ticks: str
    log_level: str


def servers(repo: Path) -> list[Server]:
    found: list[Server] = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            ticks = start_ticks(int(entry.name))
            argv = (entry / 'cmdline').read_bytes().decode().rstrip('\0').split('\0')
            if not Path(argv[0]).name.startswith('python'):
                continue
            if len(argv) < 2 or Path(argv[1]).name != 'monbat':
                continue
            # Match the service launch forms accepted by monbat.main().
            match argv[2:]:
                case [] | ['serve']:
                    level = 'info'
                case ['--log-level', level] | ['serve', '--log-level', level]:
                    pass
                case _:
                    continue
            if (entry / 'cwd').resolve(strict=True) == repo:
                if ticks is not None and start_ticks(int(entry.name)) == ticks:
                    found.append(Server(int(entry.name), ticks, level))
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            continue
    return found


def stop_server(pid: int, ticks: str, timeout: float) -> None:
    if start_ticks(pid) != ticks:
        raise DeploymentError('Server identity changed; refusing to signal it')
    os.kill(pid, signal.SIGINT)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if start_ticks(pid) != ticks:
            return
        time.sleep(0.25)
    raise DeploymentError('Graceful shutdown timed out; replacement not started')


def wait_for_readings(url: str, ids: set[str], started: float, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + '/api/latest', timeout=5) as response:
                latest = json.load(response)
            if set(latest) == ids and all(
                value['telemetry'] is not None
                and value['telemetry']['timestamp'] >= started
                and value['status'] not in ('offline', 'no-reading-yet')
                for value in latest.values()
            ):
                with urllib.request.urlopen(url + '/', timeout=5) as page:
                    if page.status == 200:
                        return
        except (OSError, ValueError, KeyError, TypeError):
            pass
        time.sleep(1)
    raise DeploymentError('HTTP/fresh Battery checks timed out; inspect service log')


def deploy(args: argparse.Namespace) -> None:
    repo = Path(args.repo).expanduser().resolve(strict=True)
    if command('git', 'status', '--porcelain', cwd=repo):
        raise DeploymentError('Checkout is not clean; preserve local edits first')
    if subprocess.run(['git', 'check-ignore', '-q', 'config.toml'], cwd=repo).returncode:
        raise DeploymentError('config.toml must be Git-ignored')
    config = tomllib.loads((repo / 'config.toml').read_text())
    ids = {b['id'] for b in config['batteries']}
    if not ids or len(ids) != len(config['batteries']):
        raise DeploymentError('Expected unique configured Battery IDs')
    host = config['server'].get('host', '127.0.0.1')
    host = '127.0.0.1' if host in ('0.0.0.0', '::') else host
    port = config['server'].get('port', 8000)
    url_host = '[' + host + ']' if ':' in host else host
    url = f'http://{url_host}:{port}'
    running = servers(repo)
    if len(running) > 1 or (not running and not args.start_stopped):
        raise DeploymentError('Expected one server in this checkout; use --start-stopped only for recovery')
    previous = command('git', 'rev-parse', 'HEAD', cwd=repo)
    level = args.log_level or (running[0].log_level if running else 'info')
    base = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    directory = (base / 'monbat/deployments' / args.id).resolve()
    if not base.is_absolute() or any(directory.is_relative_to(Path(p))
                                     for p in ('/tmp', '/var/tmp', '/private/tmp')):
        raise DeploymentError('Deployment logs/state require persistent absolute storage')
    if directory.exists():
        raise DeploymentError('Deployment ID already exists; choose a new ID')
    uv = shutil.which('uv') or str(Path.home() / '.local/bin/uv')
    if not Path(uv).is_file() or shutil.which('screen') is None:
        raise DeploymentError('Linux host requires uv and screen')
    if not args.apply:
        print(json.dumps({'id': args.id, 'previous': previous, 'candidate': args.commit,
                          'server_count': len(running), 'battery_count': len(ids),
                          'database': 'manual; config unchanged', 'action': 'plan only'}))
        return
    directory.mkdir(mode=0o700, parents=True)
    directory.chmod(0o700)
    log = directory / 'commands.log'
    state = {'previous': previous, 'candidate': args.commit, 'log_level': level,
             'status': 'preparing', 'database': 'manual'}
    def record(status: str) -> None:
        state['status'] = status
        (directory / 'state.json').write_text(json.dumps(state, indent=2))
    record('preparing')
    command('git', 'fetch', 'origin', cwd=repo, log=log, timeout=args.timeout)
    command('git', 'cat-file', '-e', args.commit + '^{commit}', cwd=repo, log=log)
    if not command('git', 'branch', '-r', '--contains', args.commit, cwd=repo, log=log):
        raise DeploymentError('Candidate is not published on a fetched remote branch')
    if running:
        print('Stopping identified server gracefully', flush=True)
        stop_server(running[0].pid, running[0].ticks, args.stop_timeout)
    with socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET) as probe:
        probe.settimeout(2)
        if probe.connect_ex((host, port)) == 0:
            raise DeploymentError('Service port remains occupied; replacement not started')
    record('stopped')
    command('git', 'switch', '--detach', args.commit, cwd=repo, log=log)
    command(uv, 'sync', '--locked', cwd=repo, log=log, timeout=args.timeout)
    session = 'monbat-' + args.id
    record('starting')
    started = time.time()
    print('Starting pinned candidate', flush=True)
    command('screen', '-L', '-Logfile', str(directory / 'service.log'), '-dmS', session,
            uv, 'run', '--frozen', '--no-sync', 'monbat', 'serve', '--log-level', level,
            cwd=repo, log=log)
    command('screen', '-S', session, '-X', 'logfile', 'flush', '1', cwd=repo, log=log)
    wait_for_readings(url, ids, started, args.timeout)
    if command('git', 'rev-parse', 'HEAD', cwd=repo) != args.commit or len(servers(repo)) != 1:
        raise DeploymentError('Final source/process check failed')
    record('deployed')
    print(json.dumps({'id': args.id, 'status': 'deployed', 'commit': args.commit,
                      'fresh_batteries': len(ids), 'database': 'unchanged'}))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True, help='Exact 40-character published commit')
    parser.add_argument('--id', required=True, help='Unique ID for persistent private logs')
    parser.add_argument('--apply', action='store_true', help='Execute; default is read-only plan')
    parser.add_argument('--start-stopped', action='store_true', help='Allow no current server during recovery')
    parser.add_argument('--log-level', choices=('debug', 'info', 'warning', 'error', 'critical'))
    parser.add_argument('--repo', default=os.environ.get('MONBAT_LINUX_REPO_PATH'))
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--stop-timeout', type=float, default=60)
    parser.add_argument('--on-host', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-f]{40}', args.commit):
        parser.error('--commit must be an exact lowercase 40-character SHA')
    if not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', args.id):
        parser.error('--id must contain 1–64 letters, digits, hyphens, or underscores')
    if not args.repo or not all(math.isfinite(t) and t > 0 for t in (args.timeout, args.stop_timeout)):
        parser.error('repo and positive finite timeouts are required')
    if args.on_host:
        if not args.apply:
            deploy(args)
            return 0
        repo = Path(args.repo).expanduser().resolve(strict=True)
        common = (repo / command('git', 'rev-parse', '--git-common-dir', cwd=repo)).resolve()
        with (common / 'monbat-deployment.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DeploymentError('Another deployment holds the checkout lock') from None
            deploy(args)
        return 0
    target = os.environ.get('MONBAT_LINUX_SSH_TARGET')
    if not target or target.startswith('-'):
        parser.error('load ignored .env.local with MONBAT_LINUX_SSH_TARGET')
    remote_python = str(Path(args.repo) / '.venv/bin/python')
    python_word = shlex.quote(remote_python)
    if remote_python.startswith('~/'):
        python_word = '"$HOME"/' + shlex.quote(remote_python[2:])
    remote = python_word + ' ' + shlex.join(['-', *sys.argv[1:], '--on-host', '--repo', args.repo])
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', target, remote],
                          input=Path(__file__).read_bytes()).returncode


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (DeploymentError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print('Deployment failed; inspect private state/logs. No automatic rollback is performed.', file=sys.stderr)
        if isinstance(error, DeploymentError):
            print(str(error), file=sys.stderr)
        sys.exit(1)
