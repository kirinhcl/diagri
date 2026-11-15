"""Does a run sheet apply the treatment its round is allocated? (spec 6.2). Pure functions.

A protocol treatment names factors; a factor whose key is a channel and whose value is a number
is a level the stage must hold, e.g. ``{"light": 70}``. A sheet applies such a factor when the
channel is host-controlled and its timed actions set that level, switching it off (level 0) at
most in between. Holding a channel only through ``retained_level`` is not applying it: that is
the state kept while a stage is paused or offline, never written while it runs.

Without this check a sheet could pass every other check, run, and be reported as a treatment the
device never received.
"""

from __future__ import annotations

from collections.abc import Iterable

from growbridge.archive.models import Channel, Ownership, ResearchProtocol, RunSheet, Treatment
from growbridge.ports import Finding

OFF = 0
CHANNELS = frozenset(c.value for c in Channel)


def levels(treatment: Treatment) -> dict[Channel, int]:
    """The channel levels a treatment fixes; other factors cannot be checked on a sheet."""
    return {
        Channel(key): int(value)
        for key, value in treatment.factors.items()
        if key in CHANNELS and isinstance(value, int | float) and not isinstance(value, bool)
    }


def allocated(protocol: ResearchProtocol, round_number: int | None) -> Treatment | None:
    """The one treatment of protocol round ``round_number``; None when there is none or several."""
    if round_number is None:
        return None
    ids = {a.treatment_id for a in protocol.allocations if a.round == round_number}
    if len(ids) != 1:
        return None
    (treatment_id,) = ids
    return next((t for t in protocol.treatments if t.id == treatment_id), None)


def _problems(sheet: RunSheet, channel: Channel, level: int) -> list[str]:
    plan = sheet.plan(channel)
    if plan is None or plan.ownership is not Ownership.HOST:
        return [f"{channel.value} is not host-controlled"]
    written = [t.level for t in sheet.timed_actions if t.channel is channel]
    if level not in written:
        return [f"no timed action sets {channel.value} to {level}"]
    other = sorted({w for w in written if w not in (level, OFF)})
    if other:
        return [f"timed actions also set {channel.value} to {other}"]
    return []


def applies(sheet: RunSheet, treatment: Treatment) -> list[str]:
    """Why ``sheet`` does not apply ``treatment``; empty when it does."""
    return [
        p for channel, level in levels(treatment).items() for p in _problems(sheet, channel, level)
    ]


def _describe(treatment: Treatment) -> str:
    fixed = ", ".join(f"{c.value} {v}" for c, v in levels(treatment).items())
    return f"{treatment.id} ({fixed})"


def check_treatment(
    sheet: RunSheet, protocol: ResearchProtocol, round_number: int | None
) -> tuple[Finding, ...]:
    """Blocking when the sheet does not apply the round's treatment, or, when the round has no
    single allocation, none of the protocol's treatments. Nothing to check: no finding."""
    checkable: Iterable[Treatment] = [t for t in protocol.treatments if levels(t)]
    if not checkable:
        return ()
    expected = allocated(protocol, round_number)
    if expected is not None and levels(expected):
        problems = applies(sheet, expected)
        if not problems:
            return ()
        message = (
            f"protocol round {round_number} is allocated treatment {_describe(expected)}: "
            + "; ".join(problems)
        )
        return (Finding(code="treatment_not_applied", message=message, blocking=True),)
    if any(not applies(sheet, t) for t in checkable):
        return ()
    names = ", ".join(_describe(t) for t in checkable)
    message = f"the sheet applies none of the protocol's treatments: {names}"
    return (Finding(code="treatment_not_applied", message=message, blocking=True),)


# --- what the device recorded ------------------------------------------------------------------

# the reading block of each level channel in a device sample (as ``control/device.MODULES``);
# the pump is an outlet that is only on or off, so a level factor cannot be read back for it
DEVICE_FIELDS = {Channel.LIGHT: "light", Channel.EXHAUST: "blower", Channel.FAN: "fan"}
MAX_OTHER_SHARE = 0.1  # readings at another non-zero level, beyond which the treatment slipped


def _recorded(data: dict, channel: Channel) -> int | None:
    block = data.get(DEVICE_FIELDS[channel])
    level = block.get("level") if isinstance(block, dict) else None
    if isinstance(level, int | float) and not isinstance(level, bool):
        return int(level)
    return None


def unread(samples: Iterable[dict], treatment: Treatment) -> list[str]:
    """The treatment's level channels for which no sample recorded a level."""
    rows = list(samples)
    return [
        channel.value
        for channel in levels(treatment)
        if channel in DEVICE_FIELDS and all(_recorded(row, channel) is None for row in rows)
    ]


def delivered(samples: Iterable[dict], treatment: Treatment) -> list[str]:
    """Why the recorded readings (sample ``data`` dicts) contradict ``treatment``; empty when
    they agree or show nothing (see ``unread``). Off (0) is allowed: a light schedule has
    nights."""
    rows = list(samples)
    problems = []
    for channel, level in levels(treatment).items():
        if channel not in DEVICE_FIELDS:
            continue
        seen = [r for r in (_recorded(row, channel) for row in rows) if r is not None]
        if not seen:
            continue
        if level not in seen:
            problems.append(f"{channel.value} was never at {level} (recorded {sorted(set(seen))})")
            continue
        other = [r for r in seen if r not in (level, OFF)]
        if len(other) > MAX_OTHER_SHARE * len(seen):
            share = round(100 * len(other) / len(seen))
            problems.append(f"{channel.value} was at other levels in {share} % of the readings")
    return problems
