"""The draft of a guided setup, worked out from its events, and the answers an existing
protocol carries into a new session. There is no stored draft: the ``chosen`` events are it."""

from collections.abc import Sequence
from typing import Any, Literal

from growbridge.archive.models import Model, ResearchProtocol
from growbridge.guide.steps import (
    ANSWERED,
    DEPENDS_ON,
    MAX_BLOCKS,
    MAX_ROUNDS,
    MAX_TREATMENTS,
    MAX_UNITS,
    StepId,
)
from growbridge.guide.store import GuideEvent
from growbridge.planning.design import randomize_series, randomize_tents

Source = Literal["system", "own", "carried"]
Status = Literal["pending", "done", "needs_review"]


class Chosen(Model):
    step: StepId
    answer: dict[str, Any]
    source: Source
    option_ids: tuple[str, ...]
    seq: int


class StepState(Model):
    step: StepId
    status: Status
    chosen: Chosen | None


def latest_chosen(events: Sequence[GuideEvent]) -> dict[StepId, Chosen]:
    """The ``chosen`` event with the highest ``seq`` of each step."""
    found: dict[str, Chosen] = {}
    for event in events:
        if event.kind != "chosen":
            continue
        current = found.get(event.step)
        if current is not None and current.seq > event.seq:
            continue
        found[event.step] = Chosen(
            step=event.step,  # type: ignore[arg-type]
            answer=event.payload["answer"],
            source=event.payload["source"],
            option_ids=tuple(event.payload.get("option_ids", ())),
            seq=event.seq,
        )
    return {step: chosen for step, chosen in found.items()}  # type: ignore[misc]


def step_states(events: Sequence[GuideEvent]) -> tuple[StepState, ...]:
    """The six answered steps. A step needs review when a step it depends on was chosen after
    it, or itself needs review. ``reopened`` events change nothing here."""
    chosen = latest_chosen(events)
    stale: dict[StepId, bool] = {}

    def needs_review(step: StepId) -> bool:
        if step not in stale:
            own = chosen.get(step)
            stale[step] = own is not None and any(
                (dep in chosen and chosen[dep].seq > own.seq) or needs_review(dep)
                for dep in DEPENDS_ON.get(step, ())
            )
        return stale[step]

    def state(step: StepId) -> StepState:
        picked = chosen.get(step)
        if picked is None:
            return StepState(step=step, status="pending", chosen=None)
        status: Status = "needs_review" if needs_review(step) else "done"
        return StepState(step=step, status=status, chosen=picked)

    return tuple(state(step) for step in ANSWERED)


def carried_answers(protocol: ResearchProtocol) -> dict[StepId, dict[str, Any]]:
    """The answers an existing protocol version gives to the six answered steps."""
    return {
        "question": {"question": protocol.question, "hypothesis": protocol.hypothesis},
        "crop": {
            "crop": protocol.crop,
            "crop_taxon": protocol.crop_taxon,
            "cultivar": protocol.cultivar,
            "batch": protocol.batch,
        },
        "treatments": {
            "treatments": [t.model_dump(mode="json") for t in protocol.treatments],
            "control_treatment_id": protocol.control_treatment_id,
        },
        "measures": {
            "variables": list(protocol.variables),
            "primary_endpoint": protocol.analysis.primary_endpoint,
        },
        "analysis": {
            "target_effect": protocol.analysis.target_effect,
            "method": protocol.analysis.method,
            "exclusion_rules": list(protocol.analysis.exclusion_rules),
            "max_missing_fraction": protocol.analysis.max_missing_fraction,
            "max_deviation_fraction": protocol.analysis.max_deviation_fraction,
            "script_sha256": protocol.analysis.script_sha256,
        },
        "scale": _carried_scale(protocol),
    }


def _carried_scale(protocol: ResearchProtocol) -> dict[str, Any]:
    """Both counts are carried exactly, with the seed and any hand-written table, so a version
    kept unchanged composes to itself even when its counts are not the ones its layout makes."""
    units = list(dict.fromkeys(a.unit for a in protocol.allocations))
    series = len(units) == 1
    kept = None
    if not _reproducible(protocol, units, series):
        kept = [a.model_dump(mode="json") for a in protocol.allocations]
    return {
        "layout": "series" if series else "tents",
        "units": units,
        "blocks": protocol.blocks,
        "rounds": protocol.rounds,
        "stages": list(protocol.stages),
        "experimental_unit": protocol.experimental_unit,
        "randomization_seed": protocol.randomization_seed,
        "allocations": kept,
    }


def _reproducible(protocol: ResearchProtocol, units: list[str], series: bool) -> bool:
    """Whether the protocol's own seed regenerates its allocations exactly. A version above the
    guide's caps, or with another number of allocations than its counts make, is not randomized
    again: its table is kept as it is."""
    ids = [t.id for t in protocol.treatments]
    if not _randomizable(protocol, len(ids), len(units), series):
        return False
    seed = protocol.randomization_seed
    try:
        if series:
            made = randomize_series(ids, protocol.blocks, seed, units[0])
        else:
            made = randomize_tents(ids, units, protocol.rounds, seed)
    except ValueError:
        return False
    return made == protocol.allocations


def _randomizable(protocol: ResearchProtocol, treatments: int, units: int, series: bool) -> bool:
    if treatments > MAX_TREATMENTS or units > MAX_UNITS:
        return False
    if series:
        count, most, expected = protocol.blocks, MAX_BLOCKS, protocol.blocks * treatments
    else:
        count, most, expected = protocol.rounds, MAX_ROUNDS, protocol.rounds * units
    return 1 <= count <= most and expected == len(protocol.allocations)
