"""What a guided step offers to choose from. Options come from the system only (the catalog, a
checked crop table, fixed lists), never from a model. Pure: same input, same options, same order."""

from typing import Any

from growbridge.archive.models import Model
from growbridge.guide.crops import CROPS
from growbridge.guide.steps import StepId
from growbridge.vocab.catalog import Catalog, Variable

DEFAULT_ANALYSIS: dict[str, Any] = {"max_missing_fraction": 0.2, "max_deviation_fraction": 0.1}
DEFAULT_EXPERIMENTAL_UNIT = "tent"


class Option(Model):
    id: str
    value: dict[str, Any]
    label_en: str
    label_zh: str


class StepOptions(Model):
    step: StepId
    options: tuple[Option, ...] = ()
    defaults: dict[str, Any] = {}


def _crop_options() -> tuple[Option, ...]:
    return tuple(
        Option(
            id=c.key,
            value={"crop": c.label_en, "crop_taxon": c.taxon},
            label_en=c.label_en,
            label_zh=c.label_zh,
        )
        for c in CROPS
    )


def _variable_options(catalog: Catalog, kinds: tuple[str, ...], shape: str) -> tuple[Option, ...]:
    def value(v: Variable) -> dict[str, Any]:
        if shape == "factor":
            return {"factor": v.id, "unit": v.unit}
        return {"variable": v.id, "kind": v.kind, "unit": v.unit}

    return tuple(
        Option(id=v.id, value=value(v), label_en=v.label_en, label_zh=v.label_zh)
        for v in catalog.variables
        if v.kind in kinds and not v.deprecated
    )


def _analysis_options() -> tuple[Option, ...]:
    return (
        Option(
            id="paired_block",
            value={"method": "paired_block"},
            label_en="Paired blocks",
            label_zh="配对区组",
        ),
        Option(
            id="two_group",
            value={"method": "two_group"},
            label_en="Two groups",
            label_zh="两组比较",
        ),
    )


def _scale_options() -> tuple[Option, ...]:
    return (
        Option(
            id="series",
            value={"layout": "series"},
            label_en="Run in series",
            label_zh="连续轮次",
        ),
        Option(
            id="tents",
            value={"layout": "tents"},
            label_en="Side by side in tents",
            label_zh="多帐篷并行",
        ),
    )


def options_for(step: StepId, catalog: Catalog, seed: int) -> StepOptions:
    if step == "crop":
        return StepOptions(step=step, options=_crop_options())
    if step == "treatments":
        return StepOptions(step=step, options=_variable_options(catalog, ("factor",), "factor"))
    if step == "measures":
        return StepOptions(
            step=step, options=_variable_options(catalog, ("sensor", "manual"), "measure")
        )
    if step == "analysis":
        return StepOptions(step=step, options=_analysis_options(), defaults=dict(DEFAULT_ANALYSIS))
    if step == "scale":
        defaults = {"randomization_seed": seed, "experimental_unit": DEFAULT_EXPERIMENTAL_UNIT}
        return StepOptions(step=step, options=_scale_options(), defaults=defaults)
    return StepOptions(step=step)
