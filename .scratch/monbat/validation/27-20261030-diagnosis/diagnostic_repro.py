import asyncio
from dataclasses import replace
import errno
import os
import subprocess
import types

import bleak
import pytest

from monbat import poller as module
from monbat.bms import BatteryConnection
from monbat.poller import Poller
from test_recovery import Rig


@pytest.fixture(autouse=True)
def diagnostic_probe(monkeypatch):
    # Causal probes only. These deliberately omit production safety checks.
    if os.environ.get('MONBAT_DIAGNOSTIC_PROBE') == 'retire-dead-client':
        original = Poller._close
        async def close(self, battery_id):
            result = await original(self, battery_id)
            if not result:
                state = self._batteries[battery_id]
                state.connection = None
                state.cleanup_pending = False
            return result
        monkeypatch.setattr(Poller, '_close', close)
    if os.environ.get('MONBAT_DIAGNOSTIC_PROBE') == 'scan-first':
        original = Poller._pass
        async def run_pass(self):
            for state in self._batteries.values():
                if state.connection is None:
                    state.rediscover = True
            await original(self)
        monkeypatch.setattr(Poller, '_pass', run_pass)


def test_available_battery_recovers_after_setup_timeout_and_dead_bus(monkeypatch):
    async def scenario():
        rig = Rig(monkeypatch)
        config = replace(rig.config, batteries=(rig.config.batteries[0],))
        rig.poller = Poller(config, rig.repo)
        rig.poller.subscribe()
        clients = []

        class Client:
            def __init__(self, device, *, timeout):
                self.number = len(clients)
                clients.append(self)

            async def connect(self):
                if self.number == 0:
                    await asyncio.Event().wait()

            async def start_notify(self, uuid, callback):
                self.callback = callback

            async def write_gatt_char(self, uuid, data, *, response):
                from test_bms import REAL_STATUS
                self.callback(0, bytearray(REAL_STATUS))

            async def disconnect(self):
                if self.number == 0:
                    raise OSError(errno.EBADF, 'Bad file descriptor')

        monkeypatch.setattr(bleak, 'BleakClient', Client)
        monkeypatch.setattr(module, 'BatteryConnection', BatteryConnection)
        await rig.poller._pass()
        for _ in range(4):
            rig.clock += 60
            await rig.poller._pass()
        print(f'clients={len(clients)} saved={len(rig.repo.saved)} cleanup_pending={rig.poller._batteries["bat-1"].cleanup_pending}')
        assert rig.repo.saved, 'Available battery never retried: dead transport retained forever'
    asyncio.run(scenario())


def test_background_pass_updates_available_batteries_after_bluez_expiry(monkeypatch):
    async def scenario():
        rig = Rig(monkeypatch, active=False)
        stale = set()
        original_factory = rig.connection

        def factory(device, timeout):
            connection = original_factory(device, timeout)
            original_connect = connection.connect
            original_close = connection.close

            async def connect():
                if id(device) in stale:
                    raise OSError('BlueZ device not found')
                await original_connect()

            async def close():
                await original_close()
                stale.add(id(device))

            connection.connect = connect
            connection.close = close
            return connection

        async def scan(*, timeout):
            from bleak.backends.device import BLEDevice
            rig.scan_count += 1
            return [BLEDevice(d.address, d.name, {}) for d in rig.devices]

        monkeypatch.setattr(module, 'BatteryConnection', factory)
        monkeypatch.setattr(module.BleakScanner, 'discover', scan)
        saved_per_pass = []
        for _ in range(5):
            before = len(rig.repo.saved)
            await rig.poller._pass()
            saved_per_pass.append(len(rig.repo.saved) - before)
            rig.clock += 1800
        print(f'saved_per_background_pass={saved_per_pass}')
        assert saved_per_pass == [2] * 5, 'Stale cache consumes alternate 30-minute collection slots'
    asyncio.run(scenario())


def test_pre26_failed_setup_cleanup_escapes_poller(monkeypatch):
    source = subprocess.run(
        ['git', 'show', 'c3ce892^:src/monbat/poller.py'],
        check=True, capture_output=True, text=True,
    ).stdout
    old_module = types.ModuleType('pre26_poller')
    exec(compile(source, 'pre26_poller.py', 'exec'), old_module.__dict__)

    async def scenario():
        rig = Rig(monkeypatch)

        class Client:
            def __init__(self, device, timeout):
                pass

            async def connect(self):
                raise TimeoutError('service discovery timeout')

            async def close(self):
                raise OSError(errno.EBADF, 'Bad file descriptor')

        monkeypatch.setattr(old_module, 'BatteryConnection', Client)
        old_poller = old_module.Poller(rig.config, rig.repo)
        with pytest.raises(OSError, match='Bad file descriptor'):
            await old_poller._pass()
        print('pre26: failed setup cleanup escapes collection pass; run() has no catch')

    asyncio.run(scenario())
