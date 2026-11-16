"""Program checks on a run sheet before human review (spec 6.2, 6.4, 7.4). Pure functions."""

from collections.abc import Iterator, Mapping

from growbridge.archive.models import (
    Channel,
    Condition,
    EvidenceCard,
    FeedbackRule,
    ManualTask,
    Ownership,
    RunSheet,
    SafetyConfig,
)
from growbridge.planning.findings import block as _block
from growbridge.planning.findings import hint as _hint
from growbridge.planning.findings import source_text
from growbridge.ports import Capabilities, Finding

USER_INPUT_PREFIX = "user:"  # an evidence reference of this form means "the user told us"

Action = tuple[str, str, Channel, int]  # source kind, source name, channel, level


def _protections(safety: SafetyConfig | None):
    return safety.rules if safety else ()


def _actions(sheet: RunSheet, safety: SafetyConfig | None) -> Iterator[Action]:
    for timed in sheet.timed_actions:
        yield "timed_action", timed.id, timed.channel, timed.level
    for rule in sheet.feedback_rules:
        yield "feedback_rule", rule.id, rule.action.channel, rule.action.level
        if rule.release is not None:
            yield "feedback_release", rule.id, rule.release.channel, rule.release.level
    for care in sheet.care_rules:
        for step in care.schedule:
            yield "care_step", f"{care.id}/{step.id}", step.channel, step.level
    for index, end in enumerate(sheet.end_actions):
        yield "end_action", str(index + 1), end.channel, end.level
    for protection in _protections(safety):
        yield "protection_rule", protection.id, protection.action.channel, protection.action.level


def _check_actions(
    sheet: RunSheet, caps: Capabilities, safety: SafetyConfig | None
) -> list[Finding]:
    findings: list[Finding] = []
    for kind, source, channel, level in _actions(sheet, safety):
        label = source_text(kind, source)
        plan = sheet.plan(channel)
        if plan is None or plan.ownership is not Ownership.HOST:
            findings.append(
                _block(
                    "device_owned_write",
                    f"{label} writes {channel.value}, which is not host-controlled in this sheet",
                    source_kind=kind,
                    source=source,
                    channel=channel.value,
                )
            )
        if channel is Channel.PUMP and level > 0:
            findings.append(
                _block(
                    "pump_action",
                    f"{label} would start the pump; no automatic step may. Plan watering as a "
                    "manual irrigation task: someone on site starts that pump run "
                    "from the stage page",
                    source_kind=kind,
                    source=source,
                )
            )
        span = caps.level_ranges.get(channel)
        if span is not None and not span[0] <= level <= span[1]:
            findings.append(
                _block(
                    "level_range",
                    f"{label} level {level} is outside the device range",
                    source_kind=kind,
                    source=source,
                    channel=channel.value,
                    level=level,
                    min=span[0],
                    max=span[1],
                )
            )
    return findings


def _check_pump_ownership(sheet: RunSheet) -> list[Finding]:
    plan = sheet.plan(Channel.PUMP)
    if plan is not None and plan.ownership is Ownership.HOST:
        return []
    return [
        _block(
            "pump_device_owned",
            "the pump must be planned as host-controlled; "
            "it may not be left to the device timer or left out",
        )
    ]


def _sensor_rules(sheet: RunSheet, safety: SafetyConfig | None):
    for rule in sheet.feedback_rules:
        yield rule.id, rule.sensor, rule.unit
    for protection in _protections(safety):
        yield protection.id, protection.sensor, protection.unit


def _check_sensors(
    sheet: RunSheet, caps: Capabilities, safety: SafetyConfig | None
) -> list[Finding]:
    findings: list[Finding] = []
    for rule_id, sensor, unit in _sensor_rules(sheet, safety):
        known = caps.sensors.get(sensor)
        if known is None:
            findings.append(
                _block(
                    "unknown_sensor",
                    f"rule {rule_id}: device has no {sensor!r}",
                    rule=rule_id,
                    sensor=sensor,
                )
            )
        elif known != unit:
            findings.append(
                _block(
                    "unit_mismatch",
                    f"rule {rule_id}: sensor {sensor!r} reports {known!r}, rule uses {unit!r}",
                    rule=rule_id,
                    sensor=sensor,
                    device_unit=known,
                    rule_unit=unit,
                )
            )
    return findings


def _is_humidity(rule: FeedbackRule) -> bool:
    name = rule.sensor.lower()
    return "humi" in name or name == "rh"


def _check_humidity(sheet: RunSheet) -> list[Finding]:
    findings = []
    for rule in sheet.feedback_rules:
        if not _is_humidity(rule):
            continue
        targets = [rule.action] + ([rule.release] if rule.release else [])
        if any(target.channel is not Channel.EXHAUST for target in targets):
            findings.append(
                _block(
                    "humidity_exhaust_only",
                    f"rule {rule.id}: humidity feedback may only move exhaust",
                    rule=rule.id,
                )
            )
    return findings


def _check_rule_conflicts(sheet: RunSheet) -> list[Finding]:
    findings = []
    rules = sheet.feedback_rules
    for index, first in enumerate(rules):
        for second in rules[index + 1 :]:
            clash = (
                first.action.channel is second.action.channel
                and first.priority == second.priority
                and first.action.level != second.action.level
            )
            if clash:
                findings.append(
                    _block(
                        "rule_conflict",
                        f"rules {first.id} and {second.id} set {first.action.channel.value} "
                        f"to different levels at priority {first.priority}",
                        rule_a=first.id,
                        rule_b=second.id,
                        channel=first.action.channel.value,
                        priority=first.priority,
                    )
                )
    return findings


def _bound(condition: Condition) -> tuple[str, float, bool]:
    side = "lower" if condition.op in (">", ">=") else "upper"
    return side, condition.value, condition.op in (">=", "<=")


def _can_overlap(first: Condition, second: Condition) -> bool:
    """Whether some reading can satisfy both conditions."""
    side_a, value_a, closed_a = _bound(first)
    side_b, value_b, closed_b = _bound(second)
    if side_a == side_b:
        return True
    lower, upper = ((value_a, closed_a), (value_b, closed_b))
    if side_a == "upper":
        lower, upper = upper, lower
    return lower[0] < upper[0] or (lower[0] == upper[0] and lower[1] and upper[1])


def _check_safety_conflicts(sheet: RunSheet, safety: SafetyConfig | None) -> list[Finding]:
    findings = []
    for rule in sheet.feedback_rules:
        for protection in _protections(safety):
            clash = (
                rule.sensor == protection.sensor
                and rule.action.channel is protection.action.channel
                and rule.action.level != protection.action.level
                and _can_overlap(rule.trigger, protection.trigger)
            )
            if clash:
                findings.append(
                    _block(
                        "safety_conflict",
                        f"rule {rule.id} can ask {rule.action.channel.value}={rule.action.level} "
                        f"while protection {protection.id} asks {protection.action.level}",
                        rule=rule.id,
                        protection=protection.id,
                        channel=rule.action.channel.value,
                        level=rule.action.level,
                        protection_level=protection.action.level,
                    )
                )
    return findings


def _check_rule_timing(sheet: RunSheet, safety: SafetyConfig | None) -> list[Finding]:
    findings = []
    interval = sheet.sampling.interval_seconds
    for rule in sheet.feedback_rules:
        if rule.validity_seconds < interval:
            findings.append(
                _block(
                    "sampling",
                    f"rule {rule.id}: reading validity is shorter than the interval",
                    variant="validity",
                    rule=rule.id,
                    validity_seconds=rule.validity_seconds,
                    interval_seconds=interval,
                )
            )
        if rule.duration_seconds <= 0 or rule.min_switch_seconds < 0:
            findings.append(
                _block(
                    "duration",
                    f"rule {rule.id}: invalid duration or switch gap",
                    variant="rule",
                    rule=rule.id,
                    duration_seconds=rule.duration_seconds,
                    min_switch_seconds=rule.min_switch_seconds,
                )
            )
    for protection in _protections(safety):
        if protection.duration_seconds <= 0:
            findings.append(
                _block(
                    "duration",
                    f"protection {protection.id}: invalid duration",
                    variant="protection",
                    protection=protection.id,
                    duration_seconds=protection.duration_seconds,
                )
            )
    return findings


def _check_numbers(sheet: RunSheet, safety: SafetyConfig | None) -> list[Finding]:
    findings = []
    sampling = sheet.sampling
    if sampling.interval_seconds <= 0:
        findings.append(
            _block(
                "sampling",
                "sampling interval must be positive",
                variant="interval",
                interval_seconds=sampling.interval_seconds,
            )
        )
    if sampling.max_gap_seconds < sampling.interval_seconds:
        findings.append(
            _block(
                "sampling",
                "max gap is shorter than the sampling interval",
                variant="max_gap",
                max_gap_seconds=sampling.max_gap_seconds,
            )
        )
    findings += _check_rule_timing(sheet, safety)
    if sheet.duration_seconds <= 0:
        findings.append(
            _block(
                "duration",
                "run duration must be positive",
                variant="run",
                duration_seconds=sheet.duration_seconds,
            )
        )
    if sheet.max_wait_seconds <= 0:
        findings.append(
            _block(
                "wait",
                "maximum wait must be positive",
                max_wait_seconds=sheet.max_wait_seconds,
            )
        )
    return findings


def _hints(sheet: RunSheet) -> list[Finding]:
    findings = [
        _hint(
            "missing_tolerance",
            f"{plan.channel.value}: no maximum tolerated outage given",
            channel=plan.channel.value,
        )
        for plan in sheet.channels
        if plan.ownership is Ownership.HOST and plan.max_tolerance_seconds is None
    ]
    findings += [_manual_hint(task) for task in sheet.manual_tasks]
    return findings


def _manual_hint(task: ManualTask) -> Finding:
    text = f"manual {task.kind} {task.id} needs the user at {task.at}"
    if task.seconds is None:
        return _hint("manual_task", text, task_kind=task.kind, task_id=task.id, at_local=task.at)
    text += f": an on-site operator starts a {task.seconds:g} s pump run from the stage page"
    return _hint(
        "manual_task",
        text,
        variant="irrigation",
        task_id=task.id,
        at_local=task.at,
        seconds=task.seconds,
    )


def validate_run_sheet(
    run_sheet: RunSheet, capabilities: Capabilities, safety: SafetyConfig | None = None
) -> tuple[Finding, ...]:
    return (
        *_check_actions(run_sheet, capabilities, safety),
        *_check_pump_ownership(run_sheet),
        *_check_sensors(run_sheet, capabilities, safety),
        *_check_humidity(run_sheet),
        *_check_rule_conflicts(run_sheet),
        *_check_safety_conflicts(run_sheet, safety),
        *_check_numbers(run_sheet, safety),
        *_hints(run_sheet),
    )


def _evidence_refs(sheet: RunSheet) -> Iterator[tuple[str, str, str | None]]:
    for timed in sheet.timed_actions:
        yield "timed_action", timed.id, timed.evidence
    for rule in sheet.feedback_rules:
        yield "feedback_rule", rule.id, rule.evidence
    for care in sheet.care_rules:
        for step in care.schedule:
            yield "care_step", f"{care.id}/{step.id}", step.evidence


def check_evidence(run_sheet: RunSheet, cards: Mapping[str, EvidenceCard]) -> tuple[Finding, ...]:
    """Every set point must cite a card or user input; weak cards are flagged, never blocking.

    A card of any class, ``local`` included, is flagged until it is verified. ``verified`` comes
    from the cards the caller passes (the archive derives it from an operator's verification
    record), so the class a card names earns no exemption.
    """
    findings: list[Finding] = []
    for kind, source, ref in _evidence_refs(run_sheet):
        if ref is not None and ref.startswith(USER_INPUT_PREFIX):
            continue
        label = source_text(kind, source)
        card = cards.get(ref) if ref is not None else None
        if card is None:
            findings.append(
                _hint(
                    "no_evidence",
                    f"{label}: no evidence card or user input",
                    source_kind=kind,
                    source=source,
                )
            )
            continue
        if not card.verified:
            findings.append(
                _hint(
                    "unverified_source",
                    f"{label}: card {card.id} is not verified; confirm it",
                    source_kind=kind,
                    source=source,
                    card_id=card.id,
                )
            )
        if not card.calibrated:
            findings.append(
                _hint(
                    "uncalibrated",
                    f"{label}: card {card.id} is uncalibrated",
                    source_kind=kind,
                    source=source,
                    card_id=card.id,
                )
            )
    return tuple(findings)
