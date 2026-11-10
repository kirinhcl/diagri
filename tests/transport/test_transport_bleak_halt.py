import asyncio

import pytest

from growbridge.transport import BleakTransport


class FakeClient:
    def __init__(self, disconnects=True, hangs=False, raises=False):
        self.is_connected = True
        self.disconnects, self.hangs, self.raises = disconnects, hangs, raises
        self.writes: list[bytes] = []

    async def disconnect(self):
        if self.raises:
            raise OSError("bus error")
        if self.hangs:
            await asyncio.sleep(10)
        if self.disconnects:
            self.is_connected = False

    async def write_gatt_char(self, uuid, packet, response=True):
        self.writes.append(bytes(packet))


def make(client):
    transport = BleakTransport("AA:BB:CC:DD:EE:FF", None, halt_timeout=0.05)
    transport.client = client
    return transport


async def test_halt_true_when_session_is_disconnected():
    client = FakeClient()
    assert await make(client).halt() is True
    assert client.is_connected is False


async def test_halt_true_when_there_is_no_session():
    assert await make(None).halt() is True


async def test_halt_false_when_disconnect_times_out():
    assert await make(FakeClient(hangs=True)).halt() is False


async def test_halt_false_when_disconnect_raises():
    assert await make(FakeClient(raises=True)).halt() is False


async def test_halt_false_when_session_stays_connected():
    assert await make(FakeClient(disconnects=False)).halt() is False


async def test_send_stops_writing_after_halt():
    client = FakeClient(disconnects=False)  # even if the link lingers, writes must stop
    transport = make(client)
    await transport.halt()

    with pytest.raises(ConnectionError):
        await transport.send({"msgId": "m1", "method": "setLight", "params": {}})
    assert client.writes == []
