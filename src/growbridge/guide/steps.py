"""The fixed steps of a guided protocol setup, the answer a researcher gives at each, and the
checks an answer must pass. Nothing here stores anything: the draft is worked out in ``draft``."""

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator

from growbridge.archive.models import Allocation, Model, Treatment
from growbridge.vocab.catalog import Catalog
from growbridge.vocab.checks import _endpoint_problems, _factor_problems, _variable_problems
from growbridge.vocab.curie import taxon_problems

StepId = Literal[
    "question", "crop", "treatments", "measures", "analysis", "scale", "review", "round"
]
STEPS: tuple[StepId, ...] = (
    "question",
    "crop",
    "treatments",
    "measures",
    "analysis",
    "scale",
    "review",
    "round",
)
ANSWERED: tuple[StepId, ...] = STEPS[:6]

# The largest experiment the guide composes. Above them one answer would make the review and the
# design checks run long enough to hold up the event loop the device tick shares.
MAX_BLOCKS = 100  # the blocks of a series
MAX_ROUNDS = 200  # the rounds of tents side by side
MAX_UNITS = 50
MAX_TREATMENTS = 20
MAX_STAGES = 20
# The other count, which only a carried version brings back: a series runs each treatment once per
# block, and tents keep one block per round.
MAX_SERIES_ROUNDS = MAX_BLOCKS * MAX_TREATMENTS
MAX_TENT_BLOCKS = MAX_ROUNDS

# A step whose answer was made from another step's answer must be looked at again when that
# other answer changes.
DEPENDS_ON: Mapping[StepId, frozenset[StepId]] = {
    "analysis": frozenset({"treatments", "measures"}),
    "scale": frozenset({"treatments", "analysis"}),
}


class QuestionAnswer(Model):
    question: str = Field(min_length=1, max_length=2000)
    hypothesis: str = Field(default="", max_length=2000)


class CropAnswer(Model):
    crop: str = Field(max_length=200)
    crop_taxon: str
    cultivar: str = ""
    batch: str = ""


class TreatmentsAnswer(Model):
    treatments: tuple[Treatment, ...] = Field(min_length=2, max_length=MAX_TREATMENTS)
    control_treatment_id: str


class MeasuresAnswer(Model):
    variables: tuple[str, ...] = Field(min_length=1)
    primary_endpoint: str


class AnalysisAnswer(Model):
    target_effect: float
    method: Literal["paired_block", "two_group"]
    exclusion_rules: tuple[str, ...] = ()
    max_missing_fraction: float = Field(default=0.2, ge=0, le=1)
    max_deviation_fraction: float = Field(default=0.1, ge=0, le=1)
    # Mirrors AnalysisPlan.script_sha256: never shown, only carried over from an old version.
    script_sha256: str | None = None


class ScaleAnswer(Model):
    layout: Literal["series", "tents"]
    units: tuple[str, ...] = Field(min_length=1, max_length=MAX_UNITS)
    blocks: int | None = None
    rounds: int | None = None
    stages: tuple[str, ...] = Field(min_length=1, max_length=MAX_STAGES)
    experimental_unit: str = "tent"
    # These two appear only when an existing version is carried over.
    randomization_seed: int | None = None
    allocations: tuple[Allocation, ...] | None = None

    @field_validator("units", "stages")
    @classmethod
    def _names_are_filled_in_and_distinct(
        cls, names: tuple[str, ...], info: ValidationInfo
    ) -> tuple[str, ...]:
        if any(not name.strip() for name in names):
            raise ValueError(f"every one of the {info.field_name} needs a name")
        if len(set(names)) != len(names):
            raise ValueError(f"two of the {info.field_name} have the same name")
        return names

    @model_validator(mode="after")
    def _layout_is_complete(self) -> "ScaleAnswer":
        if self.layout == "series":
            _count("blocks", self.blocks, MAX_BLOCKS, needed_by="a series")
            _count("rounds", self.rounds, MAX_SERIES_ROUNDS)
            if len(self.units) != 1:
                raise ValueError("a series runs in exactly one unit")
        else:
            _count("rounds", self.rounds, MAX_ROUNDS, needed_by="tents")
            _count("blocks", self.blocks, MAX_TENT_BLOCKS)
        return self


def _count(name: str, value: int | None, most: int, needed_by: str = "") -> None:
    """A count of the scale between 1 and ``most``; it may be left out unless ``needed_by``
    names the layout that needs it."""
    if value is None:
        if needed_by:
            raise ValueError(f"{needed_by} needs {name} of at least 1")
        return
    if not 1 <= value <= most:
        raise ValueError(f"{name} must be at least 1 and at most {most}")


ANSWER_MODELS: Mapping[StepId, type[Model]] = {
    "question": QuestionAnswer,
    "crop": CropAnswer,
    "treatments": TreatmentsAnswer,
    "measures": MeasuresAnswer,
    "analysis": AnalysisAnswer,
    "scale": ScaleAnswer,
}


def parse_answer(step: StepId, raw: Mapping[str, Any]) -> Model:
    """The answer model for ``step``; ``ValueError`` when the raw answer does not fit."""
    model = ANSWER_MODELS.get(step)
    if model is None:
        raise ValueError(f"step {step} takes no answer")
    return model.model_validate(dict(raw))


def answer_problems(
    step: StepId,
    answer: Model,
    catalog: Catalog,
    declared_before: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    """What is wrong with an answer, by the same rules ``vocab.checks`` applies to a protocol.
    ``declared_before`` holds the variables earlier versions of the protocol declared, which a
    deprecated variable may keep."""
    if isinstance(answer, TreatmentsAnswer):
        return tuple(_treatment_problems(answer, catalog))
    if isinstance(answer, MeasuresAnswer):
        return tuple(_measure_problems(answer, catalog, declared_before))
    if isinstance(answer, CropAnswer):
        return tuple(taxon_problems(answer.crop_taxon, answer.cultivar))
    return ()


def _treatment_problems(answer: TreatmentsAnswer, catalog: Catalog) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for treatment in answer.treatments:
        if treatment.id in seen:
            problems.append(f"treatment id {treatment.id} is used twice")
        seen.add(treatment.id)
        for key in treatment.factors:
            problems.extend(_factor_problems(treatment.id, key, catalog))
    if answer.control_treatment_id not in seen:
        problems.append(f"the control {answer.control_treatment_id} is not one of the treatments")
    return problems


def _measure_problems(
    answer: MeasuresAnswer, catalog: Catalog, declared_before: frozenset[str]
) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for name in answer.variables:
        if name in seen:
            problems.append(f"variable {name} is listed twice")
        seen.add(name)
        problems.extend(_variable_problems(name, catalog, declared_before))
    problems.extend(_endpoint_problems(answer.primary_endpoint, seen, catalog))
    return problems
