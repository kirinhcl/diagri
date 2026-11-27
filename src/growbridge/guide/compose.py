"""Composing a protocol from the latest choices of a guided setup, and reviewing it with exactly
the checks the normal save route applies, so the review never disagrees with the save."""

from collections.abc import Mapping, Sequence

from fastapi import HTTPException

from growbridge.archive.models import Allocation, AnalysisPlan, Model, ResearchProtocol
from growbridge.guide.draft import Chosen
from growbridge.guide.steps import (
    ANSWERED,
    AnalysisAnswer,
    CropAnswer,
    MeasuresAnswer,
    QuestionAnswer,
    ScaleAnswer,
    StepId,
    TreatmentsAnswer,
    answer_problems,
    parse_answer,
)
from growbridge.planning.design import check_experimental_design, randomize_series, randomize_tents
from growbridge.ports import Finding
from growbridge.vocab.catalog import Catalog
from growbridge.vocab.checks import check_protocol
from growbridge.vocab.curie import taxon_problems
from growbridge.workbench.rounds import checked_protocol

# The most allocations the guide composes; above it a review would hold up the event loop.
MAX_ALLOCATIONS = 2000


class IncompleteDraft(ValueError):
    def __init__(self, missing: tuple[StepId, ...]) -> None:
        super().__init__("steps still to answer: " + ", ".join(missing))
        self.missing = missing


class AnswerProblem(ValueError):
    """An answer that does not fit, naming the step whose answer to change."""

    def __init__(self, step: StepId, message: str) -> None:
        super().__init__(message)
        self.step = step


class Review(Model):
    protocol: ResearchProtocol | None
    missing: tuple[StepId, ...] = ()
    problems: tuple[str, ...] = ()
    # The steps whose answers the problems come from, in step order: where to go to solve them.
    problem_steps: tuple[StepId, ...] = ()
    design: tuple[Finding, ...] = ()
    ready: bool = False


def compose(
    answers: Mapping[StepId, Chosen],
    *,
    project_id: str,
    protocol_id: str,
    version: int,
    seed: int,
) -> ResearchProtocol:
    """The protocol the latest choices make; ``IncompleteDraft`` when a step has none and
    ``AnswerProblem`` when an answer does not fit or the layout cannot be randomized."""
    missing = tuple(step for step in ANSWERED if step not in answers)
    if missing:
        raise IncompleteDraft(missing)
    parsed = {step: _parsed(step, answers[step]) for step in ANSWERED}
    question, crop, treatments, measures, analysis, scale = (parsed[s] for s in ANSWERED)
    assert isinstance(question, QuestionAnswer) and isinstance(crop, CropAnswer)
    assert isinstance(treatments, TreatmentsAnswer) and isinstance(measures, MeasuresAnswer)
    assert isinstance(analysis, AnalysisAnswer) and isinstance(scale, ScaleAnswer)
    used_seed = seed if scale.randomization_seed is None else scale.randomization_seed
    try:
        allocations, blocks, rounds = _layout(scale, treatments, used_seed)
    except ValueError as exc:
        raise AnswerProblem("scale", str(exc)) from None
    return ResearchProtocol(
        id=protocol_id,
        project_id=project_id,
        version=version,
        question=question.question,
        hypothesis=question.hypothesis,
        crop=crop.crop,
        batch=crop.batch,
        treatments=treatments.treatments,
        control_treatment_id=treatments.control_treatment_id,
        allocations=allocations,
        randomization_seed=used_seed,
        analysis=AnalysisPlan(
            primary_endpoint=measures.primary_endpoint,
            target_effect=analysis.target_effect,
            method=analysis.method,
            script_sha256=analysis.script_sha256,
            exclusion_rules=analysis.exclusion_rules,
            max_missing_fraction=analysis.max_missing_fraction,
            max_deviation_fraction=analysis.max_deviation_fraction,
        ),
        stages=scale.stages,
        rounds=rounds,
        blocks=blocks,
        experimental_unit=scale.experimental_unit,
        variables=measures.variables,
        crop_taxon=crop.crop_taxon,
        cultivar=crop.cultivar,
    )


def _parsed(step: StepId, chosen: Chosen) -> Model:
    try:
        return parse_answer(step, chosen.answer)
    except ValueError as exc:
        raise AnswerProblem(step, str(exc)) from None


def _layout(
    scale: ScaleAnswer, treatments: TreatmentsAnswer, seed: int
) -> tuple[tuple[Allocation, ...], int, int]:
    """Allocations, blocks and rounds. Allocations and counts the answer carries are used as they
    are; a count it leaves out is the one its layout makes."""
    ids = [t.id for t in treatments.treatments]
    if scale.layout == "series":
        assert scale.blocks is not None  # the answer model guarantees it
        blocks = scale.blocks
        rounds = scale.rounds if scale.rounds is not None else blocks * len(ids)
    else:
        assert scale.rounds is not None
        rounds = scale.rounds
        blocks = scale.blocks if scale.blocks is not None else rounds
    _check_allocation_count(scale, len(ids), blocks, rounds)
    if scale.allocations is not None:
        if not _table_fits(scale, ids, blocks, rounds):
            raise ValueError(KEPT_TABLE_STALE)
        return scale.allocations, blocks, rounds
    if scale.layout == "series":
        return randomize_series(ids, blocks, seed, scale.units[0]), blocks, rounds
    return randomize_tents(ids, scale.units, rounds, seed), blocks, rounds


def _check_allocation_count(scale: ScaleAnswer, treatments: int, blocks: int, rounds: int) -> None:
    """Refuse, before anything is randomized or checked, a layout with more allocations than the
    guide composes: the design checks grow with blocks times allocations."""
    if scale.allocations is not None:
        count = len(scale.allocations)
    elif scale.layout == "series":
        count = blocks * treatments
    else:
        count = rounds * len(scale.units)
    if count > MAX_ALLOCATIONS:
        raise ValueError(
            f"the layout makes {count} allocations; the guide composes at most {MAX_ALLOCATIONS}"
        )


KEPT_TABLE_STALE = (
    "the kept allocation table no longer fits the scale; choose the scale again to re-randomize"
)


def _table_fits(scale: ScaleAnswer, ids: Sequence[str], blocks: int, rounds: int) -> bool:
    """Whether the allocations a scale answer carries still match its units, counts and the
    treatments, so a changed scale never reuses a table made for another one."""
    table = scale.allocations or ()
    if {a.unit for a in table} != set(scale.units):
        return False
    if len({a.round for a in table}) != rounds:
        return False
    if scale.layout == "series" and len({a.block for a in table}) != blocks:
        return False
    return {a.treatment_id for a in table} == set(ids)


def new_protocol_id(project_id: str, taken: Sequence[str], count: int) -> str:
    """The id the web form proposes: ``protocol-<n>-<last 6 of the project id>``, with ``n``
    counted up from ``count + 1`` to the first number not taken."""
    used = set(taken)
    number = count + 1
    while f"protocol-{number}-{project_id[-6:]}" in used:
        number += 1
    return f"protocol-{number}-{project_id[-6:]}"


def next_version(versions: Sequence[int]) -> int:
    return max(versions) + 1 if versions else 1


def review(
    answers: Mapping[StepId, Chosen],
    *,
    project_id: str,
    protocol_id: str,
    version: int,
    seed: int,
    catalog: Catalog,
    declared_before: frozenset[str],
) -> Review:
    """Compose, then apply what the save route applies: ``checked_protocol``, the catalog and
    taxon checks, and the design findings. Nothing is raised for a draft that is not fit."""
    try:
        composed = compose(
            answers, project_id=project_id, protocol_id=protocol_id, version=version, seed=seed
        )
    except IncompleteDraft as exc:
        return Review(protocol=None, missing=exc.missing)
    except AnswerProblem as exc:
        return Review(protocol=None, problems=(str(exc),), problem_steps=(exc.step,))
    except ValueError as exc:
        return Review(protocol=None, problems=(str(exc),))
    try:
        checked = checked_protocol(composed)
    except HTTPException as exc:
        return Review(protocol=None, problems=(str(exc.detail["message"]),))
    problems = (
        *check_protocol(checked, catalog, declared_before),
        *taxon_problems(checked.crop_taxon, checked.cultivar),
    )
    steps = _problem_steps(answers, catalog, declared_before) if problems else ()
    design = check_experimental_design(checked)
    ready = not problems and not any(finding.blocking for finding in design)
    return Review(
        protocol=checked, problems=problems, problem_steps=steps, design=design, ready=ready
    )


def _problem_steps(
    answers: Mapping[StepId, Chosen], catalog: Catalog, declared_before: frozenset[str]
) -> tuple[StepId, ...]:
    """The steps whose answers break a catalog or species rule, by the same rules step by step."""
    return tuple(
        step
        for step in ANSWERED
        if answer_problems(step, parse_answer(step, answers[step].answer), catalog, declared_before)
    )


def edited_fields(composed: ResearchProtocol, saved: ResearchProtocol) -> tuple[str, ...]:
    """The top-level fields of two protocols that differ; those of ``analysis`` are named
    ``analysis.<field>``. Sorted."""
    names: list[str] = []
    for name in ResearchProtocol.model_fields:
        mine, theirs = getattr(composed, name), getattr(saved, name)
        if mine == theirs:
            continue
        if name == "analysis":
            names.extend(
                f"analysis.{field}"
                for field in AnalysisPlan.model_fields
                if getattr(mine, field) != getattr(theirs, field)
            )
        else:
            names.append(name)
    return tuple(sorted(names))
