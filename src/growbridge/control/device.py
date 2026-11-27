"""Channel mapping, writes and read-back for the AC5 (spec 7.2, 7.6, 7.9).

LIGHT, EXHAUST and FAN are device modules (``light``, ``blower``, ``fan``); PUMP is a power
outlet. Every write forces ``modeType=0`` (manual) and is confirmed by reading back both the
instant state (``getDevSta``) and the channel mode (``getConfigFile``).
"""

import asyncio
import copy
import math
from typing import Any, NamedTuple

from growbridge.archive.ids import content_digest
from growbridge.archive.models import LEVEL_RANGES, ActionState, Channel
from growbridge.ports import Capabilities, DeviceState, Reading
from growbridge.service import Bridge, BridgeError

MODULES: dict[Channel, str] = {
    Channel.LIGHT: "light",
    Channel.EXHAUST: "blower",
    Channel.FAN: "fan",
}
SENSORS = {
    "temp": "C",
    "humi": "%",
    "vpd": "kPa",
    "co2": "ppm",
    "ppfd": "umol/m2/s",
    "tempSoil": "C",
}
PROTOCOL_VERSION = 1
READBACK_POLLS = 3
REJECTED = "Device rejected"
NOT_SENT = "not sent"  # an outcome error that starts so: the write never left the host


CODES_THAT_CHANGED_NOTHING = frozenset({"not_sent", "device_rejected"})


def changed_nothing(state: ActionState, error: str | None, error_code: str | None = None) -> bool:
    """Whether a write certainly left the device as it was: refused before sending (pending),
    voided, not sent, or rejected by the device. A read-back mismatch, a wrong mode or an
    unknown outcome may have changed something. The code decides when there is one; a record
    from before codes is judged by the start of its English text."""
    if state in (ActionState.PENDING, ActionState.VOID):
        return True
    if state is not ActionState.FAILED:
        return False
    if error_code is not None:
        return error_code in CODES_THAT_CHANGED_NOTHING
    return (error or "").startswith((NOT_SENT, REJECTED))


class Outcome(NamedTuple):
    state: ActionState
    error: str | None = None
    error_code: str | None = None  # a receipt message code for ``error``
    error_params: dict[str, Any] = {}  # noqa: RUF012  # never mutated; copied when stored


CONFIRMED = Outcome(ActionState.CONFIRMED)


class DeviceIO:
    def __init__(self, bridge: Bridge):
        self.bridge = bridge

    def outlets(self) -> dict[Channel, int]:
        settings = self.bridge.settings
        return {
            Channel.LIGHT: settings.light_outlet,
            Channel.EXHAUST: settings.exhaust_outlet,
            Channel.FAN: settings.fan_outlet,
            Channel.PUMP: settings.pump_outlet,
        }

    def capabilities(self) -> Capabilities:
        outlets = self.outlets()
        version = content_digest(
            {
                "outlets": {channel.value: number for channel, number in outlets.items()},
                "ranges": {channel.value: list(span) for channel, span in LEVEL_RANGES.items()},
                "sensors": SENSORS,
                "protocol": PROTOCOL_VERSION,
            }
        )[:16]
        return Capabilities(
            version=version,
            sensors=dict(SENSORS),
            level_ranges=dict(LEVEL_RANGES),
            outlets=outlets,
        )

    def readings(self) -> tuple[Reading, ...]:
        bridge = self.bridge
        sensors = bridge.data.get("sensor") if isinstance(bridge.data, dict) else None
        if not bridge.received_monotonic or not isinstance(sensors, dict):
            return ()
        found = []
        for name, unit in SENSORS.items():
            if name not in sensors:
                continue
            value = sensors[name]
            usable = isinstance(value, (int, float)) and not isinstance(value, bool)
            usable = usable and math.isfinite(value)
            found.append(
                Reading(
                    sensor=name,
                    value=float(value) if usable else None,
                    unit=unit,
                    at=bridge.received_at,
                    mono=bridge.received_monotonic,
                    quality="ok" if usable else "invalid",
                )
            )
        return tuple(found)

    # --- reading ------------------------------------------------------------------------------

    def _pump_key(self) -> str:
        return f"O{self.bridge.settings.pump_outlet}"

    def pump_on(self, data: dict[str, Any]) -> bool | None:
        """The pump outlet's on/off from a status; ``None`` when it is missing or malformed."""
        return _outlet_on(self._pump_outlet(data))

    def _pump_outlet(self, data: dict[str, Any]) -> object:
        outlets = data.get("outlet")
        return outlets.get(self._pump_key()) if isinstance(outlets, dict) else None

    def levels_from(self, data: dict[str, Any]) -> dict[Channel, int]:
        levels: dict[Channel, int] = {}
        for channel, module in MODULES.items():
            block = data.get(module)
            if isinstance(block, dict):
                levels[channel] = int(block.get("level", 0)) if block.get("on") else 0
        pump = self.pump_on(data)
        if pump is not None:  # a malformed outlet never reads as a confirmed level
            levels[Channel.PUMP] = int(pump)
        return levels

    def modes_from(self, config: dict[str, Any]) -> dict[Channel, int]:
        modes: dict[Channel, int] = {}
        for channel, module in MODULES.items():
            block = config.get("device", {}).get(module)
            if isinstance(block, dict) and "modeType" in block:
                modes[channel] = int(block["modeType"])
        outlet = config.get("outlet", {}).get(self._pump_key())
        if isinstance(outlet, dict) and "modeType" in outlet:
            modes[Channel.PUMP] = int(outlet["modeType"])
        return modes

    async def read_state(self, at: float) -> DeviceState:
        status = await self.bridge.request("getDevSta")
        config = await self.bridge.configuration()
        return DeviceState(
            levels=self.levels_from(status["data"]), modes=self.modes_from(config), at=at
        )

    # --- writing ------------------------------------------------------------------------------

    def params(self, config: dict[str, Any], channel: Channel, level: int) -> dict[str, Any]:
        if channel is Channel.PUMP:
            return dict(self.bridge.outlet_params(config, self.bridge.settings.pump_outlet, level))
        module = MODULES[channel]
        block = config["device"].get(module)
        if not isinstance(block, dict):
            raise BridgeError(f"{module} is absent from the live configuration")
        block = copy.deepcopy(block)
        block.update(modeType=0, mOnOff=int(level > 0), mLevel=level)
        if module == "blower" and "maxSpeed" in block:
            block["maxSpeed"] = level
        return {"keyPath": ["device", module], module: block}

    async def write(self, channel: Channel, level: int) -> Outcome:
        """Send one write and read it back. Never raises for device or link trouble."""
        try:
            config = await self.bridge.configuration()
            params = self.params(config, channel, level)
        except (BridgeError, ConnectionError, KeyError, TypeError) as error:
            return Outcome(ActionState.FAILED, f"{NOT_SENT}: {error}", error_code="not_sent")
        failed = await self._send_field(params)
        return failed or await self.confirm(channel, level)

    async def _send_field(self, params: dict[str, Any]) -> Outcome | None:
        """Send one ``setConfigField``; the failed outcome, or None once the device answered."""
        try:
            await self.bridge.request("setConfigField", params)
        except BridgeError as error:
            if str(error).startswith(REJECTED):
                return Outcome(ActionState.FAILED, str(error), error_code="device_rejected")
            return Outcome(ActionState.UNKNOWN, f"no receipt: {error}", error_code="no_receipt")
        except (ConnectionError, OSError) as error:
            return Outcome(
                ActionState.UNKNOWN, f"link broke while sending: {error}", error_code="link_broke"
            )
        return None

    # --- whole-block snapshot and restore (device tests) ----------------------------------------

    def key_path(self, channel: Channel) -> tuple[str, str]:
        """Where a channel's block lives in the configuration file."""
        if channel is Channel.PUMP:
            return ("outlet", self._pump_key())
        return ("device", MODULES[channel])

    async def read_block(self, channel: Channel) -> tuple[dict[str, Any], int | None]:
        """A copy of the channel's configuration block and its instant level; raises when the
        device cannot be read or the block is missing."""
        section, key = self.key_path(channel)
        block = (await self.bridge.configuration()).get(section, {}).get(key)
        if not isinstance(block, dict):
            raise BridgeError(f"{key} is absent from the live configuration")
        status = await self.bridge.request("getDevSta")
        return copy.deepcopy(block), self.levels_from(status["data"]).get(channel)

    async def write_block(self, channel: Channel, block: dict[str, Any], level: int) -> Outcome:
        """Write a whole block back unchanged and read it back. Never raises for device or
        link trouble."""
        section, key = self.key_path(channel)
        failed = await self._send_field({"keyPath": [section, key], key: copy.deepcopy(block)})
        return failed or await self.confirm_block(channel, block, level)

    async def confirm_block(self, channel: Channel, block: dict[str, Any], level: int) -> Outcome:
        """Confirmed when the read-back mode is the block's; a manual block also by level. The
        AC5's own program may change other fields of a non-manual block at any time."""
        mode = block.get("modeType")
        if mode == 0:
            return await self.confirm(channel, level)
        try:
            actual = self.modes_from(await self.bridge.configuration()).get(channel)
        except (BridgeError, ConnectionError, OSError) as error:
            return Outcome(
                ActionState.UNKNOWN,
                f"read-back unavailable: {error}",
                error_code="readback_unavailable",
            )
        if actual != mode:
            return Outcome(
                ActionState.FAILED,
                f"read-back mode is {actual}, expected {mode}",
                error_code="readback_mode",
                error_params={"mode": actual},
            )
        return CONFIRMED

    async def confirm(self, channel: Channel, level: int) -> Outcome:
        try:
            for attempt in range(READBACK_POLLS):
                status = await self.bridge.request("getDevSta")
                if self.levels_from(status["data"]).get(channel) == level:
                    break
                if attempt + 1 < READBACK_POLLS:
                    await asyncio.sleep(self.bridge.readback_interval)
            else:
                return Outcome(
                    ActionState.FAILED,
                    f"read-back level differs from {level}",
                    error_code="readback_level",
                    error_params={"channel": channel.value, "expected": level},
                )
            mode = self.modes_from(await self.bridge.configuration()).get(channel)
        except (BridgeError, ConnectionError, OSError) as error:
            return Outcome(
                ActionState.UNKNOWN,
                f"read-back unavailable: {error}",
                error_code="readback_unavailable",
            )
        if mode != 0:
            return Outcome(
                ActionState.FAILED,
                f"read-back mode is {mode}, expected 0",
                error_code="readback_mode",
                error_params={"mode": mode},
            )
        return CONFIRMED


def _outlet_on(outlet: object) -> bool | None:
    """An outlet block's ``on``: a bool, or a finite number (non-zero is on); else ``None``."""
    if not isinstance(outlet, dict):
        return None
    value = outlet.get("on")
    if isinstance(value, bool):
        return value
    if not isinstance(value, int | float):
        return None
    try:
        return value != 0 if math.isfinite(value) else None
    except OverflowError:  # an int beyond float range
        return None
