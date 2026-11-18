"""Design-matched statistics for blocked treatment comparisons (architecture doc §9.1, §9.3).

The experimental unit is a tent in a round, not a plant or a measurement day: plants and days
inside one unit are averaged into a single independent value first. Treatments are then compared
within blocks and tested with an exact sign-flip permutation test on the block differences.
"""

import itertools
import random
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from statistics import fmean
from typing import Any

from pydantic import Field

from growbridge.archive.models import Allocation, ManualMeasurement, Model
from growbridge.codes import checked
from growbridge.planning.treatment import unit_of
from growbridge.vocab import Catalog, packaged_catalog

MIN_BLOCKS = 2
MAX_EXACT_BLOCKS = 20
SAMPLED_FLIPS = 20_000
SAMPLING_SEED = 0
TOLERANCE = 1e-9


class BlockEstimate(Model):
    effect: float
    blocks: int
    p_value: float | None
    estimable: bool
    note: str = ""
    note_code: str = ""  # the code of ``note`` in the "estimate" family; "" for an exact estimate
    note_params: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class UnitTable:
    values: dict[tuple[int, str], float]
    dropped: tuple[str, ...]  # measurements that map to no allocation
    excluded: tuple[str, ...]  # measurements of failed rounds
    unresolved: tuple[str, ...] = ()  # uncorrected measurements whose metric the catalog lacks


def unit_table(
    measurements: Sequence[ManualMeasurement],
    allocations: Sequence[Allocation],
    metric: str,
    round_of: Mapping[str, int],
    failed_rounds: Collection[int] = (),
    catalog: Catalog | None = None,
) -> UnitTable:
    """Mean of ``metric`` per (block, treatment); each unit contributes one value only."""
    corrected = {item.corrects for item in measurements if item.corrects}
    catalog = catalog or packaged_catalog()
    current = [item for item in measurements if item.id not in corrected]
    relevant = [item for item in current if catalog.same(item.metric, metric)]
    unresolved = tuple(item.id for item in current if catalog.resolve(item.metric) is None)
    if len({item.unit for item in relevant}) > 1:
        raise ValueError(f"mixed units for metric {metric}: {sorted({i.unit for i in relevant})}")
    per_unit: dict[tuple[int, str], list[float]] = defaultdict(list)
    homes: dict[tuple[int, str], Allocation] = {}
    dropped: list[str] = []
    excluded: list[str] = []
    for item in relevant:
        round_ = round_of.get(item.experiment_id)
        home = None if round_ is None else unit_of(allocations, round_, item.position)
        if home is None:
            dropped.append(item.id)
        elif home.round in failed_rounds:
            excluded.append(item.id)
        else:
            per_unit[(home.round, home.unit)].append(item.value)
            homes[(home.round, home.unit)] = home
    per_cell: dict[tuple[int, str], list[float]] = defaultdict(list)
    for key, values in per_unit.items():
        home = homes[key]
        per_cell[(home.block, home.treatment_id)].append(fmean(values))
    cells = {cell: fmean(values) for cell, values in per_cell.items()}
    return UnitTable(cells, tuple(dropped), tuple(excluded), unresolved)


def unit_means(
    measurements: Sequence[ManualMeasurement],
    allocations: Sequence[Allocation],
    metric: str,
    round_of: Mapping[str, int],
    failed_rounds: Collection[int] = (),
    catalog: Catalog | None = None,
) -> dict[tuple[int, str], float]:
    return unit_table(measurements, allocations, metric, round_of, failed_rounds, catalog).values


def _permutation_p(differences: list[float]) -> tuple[float, bool]:
    observed = abs(sum(differences))
    slack = TOLERANCE * max(1.0, sum(abs(item) for item in differences))
    if len(differences) <= MAX_EXACT_BLOCKS:
        flips = itertools.product((1, -1), repeat=len(differences))
        total = 2 ** len(differences)
        extra = 0
        sampled = False
    else:
        generator = random.Random(SAMPLING_SEED)
        flips = (
            tuple(generator.choice((1, -1)) for _ in differences) for _ in range(SAMPLED_FLIPS)
        )
        total = SAMPLED_FLIPS
        extra = 1  # the observed assignment counts as one permutation: p is never 0
        sampled = True
    hits = sum(
        1
        for signs in flips
        if abs(sum(sign * item for sign, item in zip(signs, differences, strict=True)))
        >= observed - slack
    )
    return (hits + extra) / (total + extra), sampled


def paired_block_estimate(
    values: Mapping[tuple[int, str], float], control: str, treatment: str
) -> BlockEstimate:
    blocks = sorted({block for block, _ in values})
    differences = [
        values[(block, treatment)] - values[(block, control)]
        for block in blocks
        if (block, treatment) in values and (block, control) in values
    ]
    if len(differences) < MIN_BLOCKS:
        effect = fmean(differences) if differences else 0.0
        note = f"fewer than {MIN_BLOCKS} complete blocks; no treatment effect can be estimated"
        return BlockEstimate(
            effect=effect,
            blocks=len(differences),
            p_value=None,
            estimable=False,
            note=note,
            note_code="too_few_blocks",
            note_params=checked(
                "estimate", "too_few_blocks", {"blocks": len(differences), "min_blocks": MIN_BLOCKS}
            ),
        )
    p_value, sampled = _permutation_p(differences)
    if not sampled:
        return BlockEstimate(
            effect=fmean(differences), blocks=len(differences), p_value=p_value, estimable=True
        )
    return BlockEstimate(
        effect=fmean(differences),
        blocks=len(differences),
        p_value=p_value,
        estimable=True,
        note="p-value approximated by sampled sign flips",
        note_code="sampled_p",
        note_params=checked(
            "estimate", "sampled_p", {"flips": SAMPLED_FLIPS, "blocks": len(differences)}
        ),
    )
