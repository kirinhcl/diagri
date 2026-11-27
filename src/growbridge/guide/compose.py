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
    parse_answer,
)
from growbridge.planning.design import check_experimental_design, randomize_series, randomize_tents
from growbridge.ports import Finding
from growbridge.vocab.catalog import Catalog
from growbridge.vocab.checks import check_protocol
from growbridge.vocab.curie import taxon_problems
from growbridge.workbench.rounds import checked_protocol


class IncompleteDraft(ValueError):
    def __init__(self, missing: tuple[StepId, ...]) -> None:
        super().__init__("steps still to answer: " + ", ".join(missing))
        self.missing = missing


class Review(Model):
    protocol: ResearchProtocol | None
    missing: tuple[StepId, ...] = ()
    problems: tuple[str, ...] = ()
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
    ``ValueError`` when an answer does not fit or the layout cannot be randomized."""
    missing = tuple(step for step in ANSWERED if step not in answers)
    if missing:
        raise IncompleteDraft(missing)
    parsed = {step: parse_answer(step, answers[step].answer) for step in ANSWERED}
    question, crop, treatments, measures, analysis, scale = (parsed[s] for s in ANSWERED)
    assert isinstance(question, QuestionAnswer) and isinstance(crop, CropAnswer)
    assert isinstance(treatments, TreatmentsAnswer) and isinstance(measures, MeasuresAnswer)
    assert isinstance(analysis, AnalysisAnswer) and isinstance(scale, ScaleAnswer)
    used_seed = seed if scale.randomization_seed is None else scale.randomization_seed
    allocations, blocks, rounds = _layout(scale, treatments, used_seed)
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


def _layout(
    scale: ScaleAnswer, treatments: TreatmentsAnswer, seed: int
) -> tuple[tuple[Allocation, ...], int, int]:
    """Allocations, blocks and rounds. Allocations the answer carries are used as they are."""
    ids = [t.id for t in treatments.treatments]
    if scale.layout == "series":
        assert scale.blocks is not None  # the answer model guarantees it
        blocks, rounds = scale.blocks, scale.blocks * len(ids)
    else:
        assert scale.rounds is not None
        blocks = rounds = scale.rounds
    if scale.allocations is not None:
        return scale.allocations, blocks, rounds
    if scale.layout == "series":
        return randomize_series(ids, blocks, seed, scale.units[0]), blocks, rounds
    return randomize_tents(ids, scale.units, rounds, seed), blocks, rounds


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
    design = check_experimental_design(checked)
    ready = not problems and not any(finding.blocking for finding in design)
    return Review(protocol=checked, problems=problems, design=design, ready=ready)


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
