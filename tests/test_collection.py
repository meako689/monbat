"""Collection behavior without a physical adapter."""
import asyncio
from dataclasses import replace
import json
import tomllib
from types import SimpleNamespace

import pytest
from monbat.app import build_app
from monbat.poller import Poller
from monbat import poller as module
from monbat.discover import _serialize_config, _SelectedBattery
from test_app import _make_config, _make_telemetry, StubTelemetryRepository


@pytest.mark.parametrize('limit', [1, 2])
def test_retained_connections_and_read_limit(monkeypatch, caplog, limit):
    caplog.set_level("INFO", logger="monbat.poller")
    clients = []
    active = 0
    maximum = 0
    class Connection:
        def __init__(self, device, timeout):
            self.address = device.address
            self.closed = False
            clients.append(self)
        async def connect(self):
            pass
        async def close(self):
            self.closed = True
        async def read(self):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.001)
            active -= 1
            return _make_telemetry(1000)
    async def scan(**kwargs):
        return [SimpleNamespace(address=b.address) for b in _make_config().batteries]
    monkeypatch.setattr(module, 'BatteryConnection', Connection)
    monkeypatch.setattr(module.BleakScanner, 'discover', scan)
    async def scenario():
        config = _make_config()
        config = replace(config, poller=replace(config.poller, concurrency=limit))
        repo = StubTelemetryRepository()
        poller = Poller(config, repo)
        poller.subscribe()
        await poller._pass()
        await poller._pass()
        assert len(clients) == 2
        assert not any(c.closed for c in clients)
        assert len(repo.saved) == 4
        assert maximum == limit
        poller.unsubscribe()
        poller._grace_until = 0
        await poller._pass()
        assert all(c.closed for c in clients)
        messages = [record.getMessage() for record in caplog.records]
        assert sum("connection started" in message for message in messages) == 2
        assert sum("connection finished" in message for message in messages) == 2
    asyncio.run(scenario())


def test_sse_initial_snapshot_expiry_and_disconnect(monkeypatch):
    import monbat.app as app_module
    clock = [1000.0]
    monkeypatch.setattr(app_module.time, 'time', lambda: clock[0])
    repo = StubTelemetryRepository(latest={'bat-1': _make_telemetry(990), 'bat-2': _make_telemetry(990)})
    app = build_app(_make_config(), repo, start_poller=False)
    endpoint = next(r.endpoint for r in app.routes if r.path == '/api/events')
    async def scenario():
        response = await endpoint()
        stream = response.body_iterator
        first = json.loads((await anext(stream)).removeprefix('data: '))
        assert first['summary']['available']
        clock[0] = 1100
        second = json.loads((await anext(stream)).removeprefix('data: '))
        assert not second['summary']['available']
        assert second['latest']['bat-1']['status'] == 'offline'
        await stream.aclose()
    asyncio.run(scenario())


def test_rediscovery_preserves_config_and_quotes():
    existing = _make_config(poll_interval_seconds=123)
    text = _serialize_config([_SelectedBattery('same', 'A "quoted" battery', 'opaque')], existing, 2)
    result = tomllib.loads(text)
    assert result['poller']['poll_interval_seconds'] == 123
    assert result['poller']['concurrency'] == 2
    assert result['server']['port'] == existing.server.port
    assert result['batteries'][0]['name'] == 'A "quoted" battery'


def test_browser_cadence_grace_and_shutdown(monkeypatch):
    async def scenario():
        config = _make_config(poll_interval_seconds=600)
        poller = Poller(config, StubTelemetryRepository())
        calls = []
        clock = [0.0]
        monkeypatch.setattr(module, 'monotonic', lambda: clock[0])
        async def collect():
            calls.append(clock[0])
        monkeypatch.setattr(poller, '_pass', collect)
        task = asyncio.create_task(poller.run())
        await asyncio.sleep(0)
        assert calls == [0]
        clock[0] = 1
        poller.subscribe()
        await asyncio.sleep(0.01)
        assert calls == [0, 1]
        poller.subscribe()
        await asyncio.sleep(0)
        assert len(calls) == 2
        poller.unsubscribe()
        assert poller._active()
        poller.unsubscribe()
        assert poller._active()
        clock[0] = 32
        poller._wake.set()
        await asyncio.sleep(0.01)
        assert not poller._active()
        assert len(calls) == 2
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert poller.request_refresh() == 'disabled'
    asyncio.run(scenario())
