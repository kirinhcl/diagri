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

from growbridge.archive.models import (
    Allocation,
    Channel,
    Ownership,
    ResearchProtocol,
    RunSheet,
    Treatment,
)
from growbridge.planning.findings import block as _block
from growbridge.planning.findings import treatment_name
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


def unit_of(protocol: ResearchProtocol, round_number: int, position: str) -> Allocation | None:
    """The allocation a measured ``position`` belongs to in a round, or None.

    A round with one allocation has one unit, so any position is it; otherwise the position
    must name the unit.
    """
    in_round = [a for a in protocol.allocations if a.round == round_number]
    if len(in_round) == 1:
        return in_round[0]
    return next((a for a in in_round if a.unit == position), None)


Problem = dict[str, object]  # {kind, channel, level, other}: what the console words per kind


def _problem(kind: str, channel: Channel, level: int | None, other: int | None = None) -> Problem:
    return {"kind": kind, "channel": channel.value, "level": level, "other": other}


def _problems(sheet: RunSheet, channel: Channel, level: int) -> list[Problem]:
    plan = sheet.plan(channel)
    if plan is None or plan.ownership is not Ownership.HOST:
        return [_problem("not_host", channel, None)]
    written = [t.level for t in sheet.timed_actions if t.channel is channel]
    if level not in written:
        return [_problem("no_action", channel, level)]
    other = sorted({w for w in written if w not in (level, OFF)})
    return [_problem("other_levels", channel, level, w) for w in other]


def applies(sheet: RunSheet, treatment: Treatment) -> list[Problem]:
    """Why ``sheet`` does not apply ``treatment``; empty when it does."""
    return [
        p for channel, level in levels(treatment).items() for p in _problems(sheet, channel, level)
    ]


def _problem_texts(problems: list[Problem]) -> list[str]:
    """The English wording; other levels of one channel read as one list, as before."""
    texts: list[str] = []
    others: dict[object, list[object]] = {}
    for problem in problems:
        channel, level = problem["channel"], problem["level"]
        if problem["kind"] == "not_host":
            texts.append(f"{channel} is not host-controlled")
        elif problem["kind"] == "no_action":
            texts.append(f"no timed action sets {channel} to {level}")
        else:
            others.setdefault(channel, []).append(problem["other"])
    texts += [f"timed actions also set {channel} to {levels}" for channel, levels in others.items()]
    return texts


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
            + "; ".join(_problem_texts(problems))
        )
        finding = _block(
            "treatment_not_applied",
            message,
            round=round_number,
            treatment=treatment_name(expected),
            treatment_id=expected.id,
            problems=problems,
        )
        return (finding,)
    if any(not applies(sheet, t) for t in checkable):
        return ()
    names = ", ".join(_describe(t) for t in checkable)
    message = f"the sheet applies none of the protocol's treatments: {names}"
    none = _block(
        "treatment_not_applied",
        message,
        variant="none",
        round=round_number,
        treatments=[treatment_name(t) for t in checkable],
        treatment_ids=[t.id for t in checkable],
    )
    return (none,)


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


def delivered(samples: Iterable[dict], treatment: Treatment) -> list[dict]:
    """Where the recorded readings (sample ``data`` dicts) contradict ``treatment``, as
    ``{channel, kind, level, recorded, share}``: ``never_at`` (the level never showed; ``share``
    is 0) or ``other_share`` (``share`` is the share of readings at other non-zero levels);
    empty when they agree or show nothing (see ``unread``). Off (0) is allowed: a light
    schedule has nights."""
    rows = list(samples)
    problems: list[dict] = []
    for channel, level in levels(treatment).items():
        if channel not in DEVICE_FIELDS:
            continue
        seen = [r for r in (_recorded(row, channel) for row in rows) if r is not None]
        if not seen:
            continue
        item = {"channel": channel.value, "level": level, "recorded": sorted(set(seen))}
        if level not in seen:
            problems.append({**item, "kind": "never_at", "share": 0.0})
            continue
        other = [r for r in seen if r not in (level, OFF)]
        if len(other) > MAX_OTHER_SHARE * len(seen):
            problems.append({**item, "kind": "other_share", "share": len(other) / len(seen)})
    return problems
