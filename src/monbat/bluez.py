"""Independent, bounded BlueZ connection inspection and cleanup."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from enum import StrEnum
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from dbus_fast.aio import MessageBus

logger = logging.getLogger(__name__)

_BLUEZ_SERVICE = "org.bluez"
_DEVICE_INTERFACE = "org.bluez.Device1"
_OBJECT_MANAGER_INTERFACE = "org.freedesktop.DBus.ObjectManager"


class BlueZConnectionState(StrEnum):
    ABSENT = "absent"
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    UNAVAILABLE = "unavailable"


def _new_message_bus() -> MessageBus:
    from dbus_fast import BusType
    from dbus_fast.aio import MessageBus
    from dbus_fast.auth import AuthExternal

    auth_uid: int | None = None
    try:
        auth_uid = int(os.environ.get("BLEAK_DBUS_AUTH_UID", ""))
    except ValueError:
        pass
    auth = AuthExternal(uid=auth_uid) if auth_uid is not None else None

    # This is deliberately a fresh system-bus connection, independent of the
    # possibly unusable D-Bus transport held by BleakClient.
    return MessageBus(bus_type=BusType.SYSTEM, auth=auth)


async def _managed_objects(bus: MessageBus) -> object:
    from dbus_fast import Message, MessageType

    reply = await bus.call(
        Message(
            destination=_BLUEZ_SERVICE,
            path="/",
            interface=_OBJECT_MANAGER_INTERFACE,
            member="GetManagedObjects",
        )
    )
    if reply.message_type is MessageType.ERROR:
        raise RuntimeError(reply.error_name or "BlueZ object query failed")
    body = cast(list[object], reply.body)
    if not body:
        raise RuntimeError("BlueZ returned no managed objects")
    return body[0]


def _device_properties(objects: object, address: str) -> list[tuple[str, bool | None]]:
    if not isinstance(objects, dict):
        raise ValueError("BlueZ returned an invalid managed-object list")

    matches: list[tuple[str, bool | None]] = []
    for path, interfaces in objects.items():
        if not isinstance(path, str) or not isinstance(interfaces, dict):
            continue
        raw_properties = interfaces.get(_DEVICE_INTERFACE)
        if not isinstance(raw_properties, dict):
            continue
        raw_address = raw_properties.get("Address")
        device_address = getattr(raw_address, "value", raw_address)
        if not isinstance(device_address, str) or device_address.upper() != address.upper():
            continue
        raw_connected = raw_properties.get("Connected")
        connected = getattr(raw_connected, "value", raw_connected)
        matches.append((path, connected if isinstance(connected, bool) else None))
    return matches


async def get_connection_state(address: str, timeout_seconds: float) -> BlueZConnectionState:
    """Return BlueZ's current Device1 state, or UNAVAILABLE when it is unknown."""
    if sys.platform != "linux":
        return BlueZConnectionState.UNAVAILABLE

    bus: MessageBus | None = None
    try:
        async with asyncio.timeout(timeout_seconds):
            bus = _new_message_bus()
            await bus.connect()
            objects = await _managed_objects(bus)
        matches = _device_properties(objects, address)
        if not matches:
            return BlueZConnectionState.ABSENT
        if any(connected is True for _, connected in matches):
            return BlueZConnectionState.CONNECTED
        if all(connected is False for _, connected in matches):
            return BlueZConnectionState.DISCONNECTED
        return BlueZConnectionState.UNAVAILABLE
    except Exception:
        logger.debug("BlueZ connection state unavailable address=%s", address, exc_info=True)
        return BlueZConnectionState.UNAVAILABLE
    finally:
        if bus is not None:
            bus.disconnect()


async def disconnect_device(address: str, timeout_seconds: float) -> None:
    """Ask BlueZ to disconnect matching Device1 objects over a fresh D-Bus bus."""
    if sys.platform != "linux":
        raise RuntimeError("Independent BlueZ disconnect is available only on Linux")

    from dbus_fast import Message, MessageType

    bus: MessageBus | None = None
    try:
        async with asyncio.timeout(timeout_seconds):
            bus = _new_message_bus()
            await bus.connect()
            objects = await _managed_objects(bus)
            connected_paths = [
                path for path, connected in _device_properties(objects, address)
                if connected is True
            ]
            for path in connected_paths:
                reply = await bus.call(
                    Message(
                        destination=_BLUEZ_SERVICE,
                        path=path,
                        interface=_DEVICE_INTERFACE,
                        member="Disconnect",
                    )
                )
                if reply.message_type is MessageType.ERROR:
                    raise RuntimeError(reply.error_name or "BlueZ disconnect failed")
    finally:
        if bus is not None:
            bus.disconnect()
