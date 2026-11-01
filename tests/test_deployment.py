"""Deployment safety checks without starting a server or contacting hardware."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import signal
import subprocess
import sys

import pytest

spec = importlib.util.spec_from_file_location('deploy_linux', Path(__file__).parents[1] / 'scripts/deploy_linux.py')
assert spec is not None and spec.loader is not None
deployment = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = deployment
spec.loader.exec_module(deployment)


def _stat(ticks: str) -> str:
    fields = ['S'] + ['0'] * 18 + [ticks]
    return '1234 (python worker) ' + ' '.join(fields)


def test_reused_pid_is_never_signalled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, 'read_text', lambda self, **kwargs: _stat('200'))
    def reject_signal(pid: int, sig: int) -> None:
        pytest.fail('Reused PID received a signal')
    monkeypatch.setattr(deployment.os, 'kill', reject_signal)
    with pytest.raises(deployment.DeploymentError, match='identity changed'):
        deployment.stop_server(1234, '100', 1)


def test_graceful_shutdown_timeout_stops_the_rollout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, 'read_text', lambda self, **kwargs: _stat('100'))
    clock = iter([0, 0, 2])
    monkeypatch.setattr(deployment.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(deployment.time, 'sleep', lambda _: None)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(deployment.os, 'kill', lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(deployment.DeploymentError, match='shutdown timed out'):
        deployment.stop_server(1234, '100', 1)
    assert signals == [(1234, signal.SIGINT)]


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / 'checkout'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    (repo / '.gitignore').write_text('config.toml\n')
    subprocess.run(['git', 'add', '.gitignore'], cwd=repo, check=True)
    subprocess.run(['git', '-c', 'user.name=Example', '-c', 'user.email=agent@example.invalid',
                    'commit', '-qm', 'Baseline'], cwd=repo, check=True)
    (repo / 'config.toml').write_text('''[poller]
sqlite_path = "absent-manually-prepared.db"
[server]
host = "127.0.0.1"
port = 8000
[[batteries]]
id = "bat-1"
''')
    return repo


def _args(repo: Path, *, apply: bool = False) -> argparse.Namespace:
    return argparse.Namespace(repo=str(repo), id='test-deployment', apply=apply,
                              commit='a' * 40, start_stopped=True, log_level=None,
                              timeout=1, stop_timeout=1)


def test_plan_does_not_write_or_touch_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    original_iterdir = Path.iterdir
    monkeypatch.setattr(Path, 'iterdir', lambda path: iter(()) if str(path) == '/proc'
                        else original_iterdir(path))
    monkeypatch.setattr(deployment.shutil, 'which', lambda name: sys.executable)
    monkeypatch.setenv('XDG_DATA_HOME', '/synthetic-persistent-data-for-plan')
    config_before = (repo / 'config.toml').read_bytes()
    head_before = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo)
    deployment.deploy(_args(repo))
    result = json.loads(capsys.readouterr().out)
    assert result['action'] == 'plan only'
    assert result['database'] == 'manual; config unchanged'
    assert (repo / 'config.toml').read_bytes() == config_before
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo) == head_before
    assert not (repo / 'absent-manually-prepared.db').exists()
    assert not Path('/synthetic-persistent-data-for-plan').exists()


def test_dirty_checkout_is_preserved_before_apply(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    local = repo / 'local-work.txt'
    local.write_text('Keep this work')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo)
    with pytest.raises(deployment.DeploymentError, match='not clean'):
        deployment.deploy(_args(repo, apply=True))
    assert local.read_text() == 'Keep this work'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo) == head


def test_ssh_preserves_repo_argument_without_shell_interpolation(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = '/srv/checkout with spaces/$(touch must-not-run)'
    monkeypatch.setattr(sys, 'argv', ['deploy_linux.py', '--commit', 'a' * 40,
                                     '--id', 'test', '--repo', repo])
    monkeypatch.setenv('MONBAT_LINUX_SSH_TARGET', 'remote-user@host.example')
    calls: list[tuple[list[str], bytes]] = []
    def ssh(argv: list[str], *, input: bytes) -> subprocess.CompletedProcess[bytes]:
        calls.append((argv, input))
        return subprocess.CompletedProcess(argv, 0)
    monkeypatch.setattr(deployment.subprocess, 'run', ssh)
    assert deployment.main() == 0
    import shlex
    assert shlex.split(calls[0][0][-1])[-1] == repo
    assert calls[0][0][0:3] == ['ssh', '-o', 'BatchMode=yes']
    assert b'Database preparation is manual' in calls[0][1]


@pytest.mark.parametrize('argument,value', [('--commit', 'master'), ('--id', '../escape'),
                                          ('--timeout', 'nan')])
def test_invalid_inputs_fail_before_ssh(argument: str, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    values = {'--commit': 'a' * 40, '--id': 'test', '--repo': '/srv/checkout'}
    values[argument] = value
    monkeypatch.setattr(sys, 'argv', ['deploy_linux.py', *[item for pair in values.items() for item in pair]])
    def reject_ssh(*args: object, **kwargs: object) -> None:
        pytest.fail('Invalid arguments reached SSH')
    monkeypatch.setattr(deployment.subprocess, 'run', reject_ssh)
    with pytest.raises(SystemExit) as error:
        deployment.main()
    assert error.value.code == 2


def test_remote_home_path_expands_only_the_home_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = "~/checkout with spaces/$(touch must-not-run)"
    monkeypatch.setattr(sys, 'argv', ['deploy_linux.py', '--commit', 'a' * 40,
                                     '--id', 'test', '--repo', repo])
    monkeypatch.setenv('MONBAT_LINUX_SSH_TARGET', 'remote-user@host.example')
    calls: list[list[str]] = []
    def ssh(argv: list[str], *, input: bytes) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)
    monkeypatch.setattr(deployment.subprocess, 'run', ssh)
    assert deployment.main() == 0
    remote = calls[0][-1]
    assert remote.startswith('"$HOME"/\'checkout with spaces/$(touch must-not-run)/.venv/bin/python\' ')
    import shlex
    assert shlex.split(remote)[-1] == repo


@pytest.mark.parametrize('arguments,expected_level', [
    ([], 'info'),
    (['--log-level', 'debug'], 'debug'),
    (['serve'], 'info'),
    (['serve', '--log-level', 'warning'], 'warning'),
    (['discover'], None),
    (['unknown'], None),
])
def test_service_detection_matches_supported_cli_forms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    arguments: list[str], expected_level: str | None,
) -> None:
    repo = tmp_path / 'checkout'
    repo.mkdir()
    proc = tmp_path / 'proc'
    entry = proc / '1234'
    entry.mkdir(parents=True)
    (entry / 'stat').write_text(_stat('100'))
    (entry / 'cmdline').write_bytes(
        ('\0'.join(['/synthetic/bin/python', '/synthetic/bin/monbat', *arguments]) + '\0').encode()
    )
    (entry / 'cwd').symlink_to(repo, target_is_directory=True)
    original_iterdir = Path.iterdir
    original_read_text = Path.read_text
    monkeypatch.setattr(Path, 'iterdir', lambda path: proc.iterdir() if path == Path('/proc') else original_iterdir(path))
    monkeypatch.setattr(Path, 'read_text', lambda path, **kwargs: original_read_text(
        proc / path.relative_to('/proc') if path.is_relative_to('/proc') else path, **kwargs))

    found = deployment.servers(repo)

    assert found == ([] if expected_level is None else [deployment.Server(1234, '100', expected_level)])
    assert deployment.servers(tmp_path / 'different-checkout') == []
    (entry / 'cmdline').write_bytes(b'/synthetic/bin/python\0/synthetic/bin/unrelated\0serve\0')
    assert deployment.servers(repo) == []
