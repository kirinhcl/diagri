"""Randomization and experimental-design checks (spec 6.3). Pure and seed-reproducible."""

import math
import random
from collections import Counter
from collections.abc import Collection, Sequence
from itertools import groupby
from statistics import NormalDist
from typing import Literal

from growbridge.archive.models import Allocation, ResearchProtocol
from growbridge.ports import Finding

MIN_SAMPLE_SIZE = 2


def _block(code: str, message: str) -> Finding:
    return Finding(code=code, message=message, blocking=True)


def _check_treatments(treatment_ids: Sequence[str]) -> None:
    if not treatment_ids:
        raise ValueError("At least one treatment is required")
    if len(set(treatment_ids)) != len(treatment_ids):
        raise ValueError("Treatment ids must be unique")


def randomize_series(
    treatment_ids: Sequence[str], blocks: int, seed: int, unit: str = "tent-1"
) -> tuple[Allocation, ...]:
    """One tent, one round at a time: every block holds each treatment once, in seeded order."""
    _check_treatments(treatment_ids)
    if blocks < 1:
        raise ValueError("At least one block is required")
    rng = random.Random(seed)
    allocations = []
    for block in range(1, blocks + 1):
        order = list(treatment_ids)
        rng.shuffle(order)
        for position, treatment_id in enumerate(order):
            round_number = (block - 1) * len(order) + position + 1
            allocations.append(
                Allocation(round=round_number, block=block, unit=unit, treatment_id=treatment_id)
            )
    return tuple(allocations)


def randomize_tents(
    treatment_ids: Sequence[str], units: Sequence[str], rounds: int, seed: int
) -> tuple[Allocation, ...]:
    """Several tents per round: treatments are shuffled over the tents; the round is the block."""
    _check_treatments(treatment_ids)
    if not units or len(units) % len(treatment_ids) != 0:
        raise ValueError("The number of tents must be a positive multiple of the treatments")
    if rounds < 1:
        raise ValueError("At least one round is required")
    rng = random.Random(seed)
    pool = list(treatment_ids) * (len(units) // len(treatment_ids))
    allocations = []
    for round_number in range(1, rounds + 1):
        rng.shuffle(pool)
        allocations.extend(
            Allocation(round=round_number, block=round_number, unit=unit, treatment_id=treatment)
            for unit, treatment in zip(units, pool, strict=True)
        )
    return tuple(allocations)


def make_up_allocation(protocol: ResearchProtocol, failed_round: int) -> Allocation:
    """Repeat the failed round's treatment in its block under a new round number."""
    failed = next((a for a in protocol.allocations if a.round == failed_round), None)
    if failed is None:
        raise ValueError(f"Protocol has no round {failed_round}")
    newest = max(a.round for a in protocol.allocations)
    return failed.model_copy(update={"round": newest + 1})


def _unit_counts(protocol: ResearchProtocol) -> Counter[str]:
    """Experimental units (a round in a tent) per known treatment."""
    known = {t.id for t in protocol.treatments}
    seen = {(a.round, a.unit, a.treatment_id) for a in protocol.allocations}
    return Counter(treatment for _, _, treatment in seen if treatment in known)


def _check_membership(protocol: ResearchProtocol, counts: Counter[str]) -> list[Finding]:
    known = {t.id for t in protocol.treatments}
    findings = []
    unknown = sorted({a.treatment_id for a in protocol.allocations} - known)
    if unknown:
        findings.append(
            _block("unknown_treatment", f"allocations use unknown treatments {unknown}")
        )
    if protocol.control_treatment_id not in known:
        findings.append(_block("missing_control", "control treatment is not a defined treatment"))
    elif counts[protocol.control_treatment_id] == 0:
        findings.append(_block("missing_control", "control treatment is never allocated"))
    return findings


def _check_replication(protocol: ResearchProtocol, counts: Counter[str]) -> list[Finding]:
    thin = [t.id for t in protocol.treatments if counts[t.id] < 2]
    if not thin:
        return []
    return [_block("no_replication", f"treatments without two or more units: {thin}")]


def _check_blocks(protocol: ResearchProtocol) -> list[Finding]:
    known = [t.id for t in protocol.treatments]
    findings = []
    for block in sorted({a.block for a in protocol.allocations}):
        counts = Counter(a.treatment_id for a in protocol.allocations if a.block == block)
        if len({counts[treatment] for treatment in known}) > 1:
            findings.append(_block("unbalanced_block", f"block {block} is not balanced"))
    return findings


def _check_time_confounding(protocol: ResearchProtocol) -> list[Finding]:
    per_round: dict[int, set[str]] = {}
    for allocation in protocol.allocations:
        per_round.setdefault(allocation.round, set()).add(allocation.treatment_id)
    if any(len(treatments) != 1 for treatments in per_round.values()):
        return []
    sequence = [next(iter(per_round[r])) for r in sorted(per_round)]
    runs = [key for key, _ in groupby(sequence)]
    if len(set(runs)) > 1 and len(runs) == len(set(runs)):
        message = "each treatment occupies one unbroken stretch of rounds"
        return [_block("confounded_with_time", message)]
    return []


def _seed_finding(message: str) -> Finding:
    return Finding(code="seed_mismatch", message=message, blocking=False)


def _check_seed(protocol: ResearchProtocol) -> list[Finding]:
    ids = [t.id for t in protocol.treatments]
    units = list(dict.fromkeys(a.unit for a in protocol.allocations))
    if not ids or not units or len(set(ids)) != len(ids):
        return []
    seed = protocol.randomization_seed
    try:
        if len(units) == 1:
            expected = randomize_series(ids, protocol.blocks, seed, units[0])
        else:
            expected = randomize_tents(ids, units, protocol.rounds, seed)
    except ValueError:
        return [_seed_finding("allocations cannot be regenerated from the seed")]
    last_round = max(a.round for a in expected)
    planned = {a for a in protocol.allocations if a.round <= last_round}  # skip make-up rounds
    if planned == set(expected):
        return []
    return [_seed_finding("allocations do not follow from the recorded seed")]


def check_experimental_design(
    protocol: ResearchProtocol, failed_rounds: Collection[int] = ()
) -> tuple[Finding, ...]:
    """Blocking findings for unusable designs; ``seed_mismatch`` is advisory only.

    Allocations of ``failed_rounds`` (made up in the same block) are ignored for the balance,
    replication and confounding checks; the seed is judged on the original allocations.
    """
    kept = tuple(a for a in protocol.allocations if a.round not in set(failed_rounds))
    effective = protocol.model_copy(update={"allocations": kept})
    counts = _unit_counts(effective)
    return (
        *_check_membership(effective, counts),
        *_check_replication(effective, counts),
        *_check_blocks(effective),
        *_check_time_confounding(effective),
        *_check_seed(protocol),
    )


def estimate_sample_size(
    effect: float,
    sd: float,
    alpha: float = 0.05,
    power: float = 0.8,
    design: Literal["paired_block", "two_group"] = "paired_block",
) -> int:
    """Sample size: blocks (``paired_block``) or units per group (``two_group``).

    Normal approximation. For ``paired_block`` (``sd`` is the sd of within-block differences) the
    Guenther small-sample correction ``+ z_(1-alpha/2)^2 / 2`` is added, and the result is floored
    at the smallest n whose exact sign-flip permutation test can reach ``alpha``: 2^(1-n) <= alpha.
    """
    if effect <= 0 or sd <= 0:
        raise ValueError("effect and sd must be positive")
    if not 0 < alpha < 1 or not 0 < power < 1:
        raise ValueError("alpha and power must lie strictly between 0 and 1")
    normal = NormalDist()
    z_total = normal.inv_cdf(1 - alpha / 2) + normal.inv_cdf(power)
    n = (z_total * sd / effect) ** 2
    if design == "two_group":
        return max(MIN_SAMPLE_SIZE, math.ceil(2 * n))
    n += normal.inv_cdf(1 - alpha / 2) ** 2 / 2
    resolution_floor = math.ceil(1 + math.log2(1 / alpha) - 1e-9)
    return max(MIN_SAMPLE_SIZE, resolution_floor, math.ceil(n))
