"""Program checks on a run sheet before human review (spec 6.2, 6.4, 7.4). Pure functions."""

from collections.abc import Iterator, Mapping

from growbridge.archive.models import (
    Channel,
    Condition,
    EvidenceCard,
    FeedbackRule,
    Ownership,
    RunSheet,
    SafetyConfig,
)
from growbridge.ports import Capabilities, Finding

USER_INPUT_PREFIX = "user:"  # an evidence reference of this form means "the user told us"

Action = tuple[str, Channel, int]  # label, channel, level


def _block(code: str, message: str) -> Finding:
    return Finding(code=code, message=message, blocking=True)


def _hint(code: str, message: str) -> Finding:
    return Finding(code=code, message=message, blocking=False)


def _protections(safety: SafetyConfig | None):
    return safety.rules if safety else ()


def _actions(sheet: RunSheet, safety: SafetyConfig | None) -> Iterator[Action]:
    for timed in sheet.timed_actions:
        yield f"timed action {timed.id}", timed.channel, timed.level
    for rule in sheet.feedback_rules:
        yield f"feedback rule {rule.id}", rule.action.channel, rule.action.level
        if rule.release is not None:
            yield f"feedback rule {rule.id} release", rule.release.channel, rule.release.level
    for care in sheet.care_rules:
        for step in care.schedule:
            yield f"care rule {care.id}/{step.id}", step.channel, step.level
    for index, end in enumerate(sheet.end_actions):
        yield f"end action {index + 1}", end.channel, end.level
    for protection in _protections(safety):
        yield f"protection rule {protection.id}", protection.action.channel, protection.action.level


def _check_actions(
    sheet: RunSheet, caps: Capabilities, safety: SafetyConfig | None
) -> list[Finding]:
    findings: list[Finding] = []
    for label, channel, level in _actions(sheet, safety):
        plan = sheet.plan(channel)
        if plan is None or plan.ownership is not Ownership.HOST:
            findings.append(
                _block(
                    "device_owned_write",
                    f"{label} writes {channel.value}, which is not host-controlled in this sheet",
                )
            )
        if channel is Channel.PUMP and level > 0:
            findings.append(_block("pump_action", f"{label} would start the pump"))
        span = caps.level_ranges.get(channel)
        if span is not None and not span[0] <= level <= span[1]:
            findings.append(
                _block("level_range", f"{label} level {level} is outside the device range")
            )
    return findings


def _check_pump_ownership(sheet: RunSheet) -> list[Finding]:
    plan = sheet.plan(Channel.PUMP)
    if plan is not None and plan.ownership is Ownership.DEVICE:
        return [_block("pump_device_owned", "the pump may not be left to the device timer")]
    return []


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
            findings.append(_block("unknown_sensor", f"rule {rule_id}: device has no {sensor!r}"))
        elif known != unit:
            findings.append(
                _block(
                    "unit_mismatch",
                    f"rule {rule_id}: sensor {sensor!r} reports {known!r}, rule uses {unit!r}",
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
                    )
                )
    return findings


def _check_rule_timing(sheet: RunSheet, safety: SafetyConfig | None) -> list[Finding]:
    findings = []
    interval = sheet.sampling.interval_seconds
    for rule in sheet.feedback_rules:
        if rule.validity_seconds < interval:
            findings.append(
                _block("sampling", f"rule {rule.id}: reading validity is shorter than the interval")
            )
        if rule.duration_seconds <= 0 or rule.min_switch_seconds < 0:
            findings.append(_block("duration", f"rule {rule.id}: invalid duration or switch gap"))
    for protection in _protections(safety):
        if protection.duration_seconds <= 0:
            findings.append(_block("duration", f"protection {protection.id}: invalid duration"))
    return findings


def _check_numbers(sheet: RunSheet, safety: SafetyConfig | None) -> list[Finding]:
    findings = []
    sampling = sheet.sampling
    if sampling.interval_seconds <= 0:
        findings.append(_block("sampling", "sampling interval must be positive"))
    if sampling.max_gap_seconds < sampling.interval_seconds:
        findings.append(_block("sampling", "max gap is shorter than the sampling interval"))
    findings += _check_rule_timing(sheet, safety)
    if sheet.duration_seconds <= 0:
        findings.append(_block("duration", "run duration must be positive"))
    if sheet.max_wait_seconds <= 0:
        findings.append(_block("wait", "maximum wait must be positive"))
    return findings


def _hints(sheet: RunSheet) -> list[Finding]:
    findings = [
        _hint("missing_tolerance", f"{plan.channel.value}: no maximum tolerated outage given")
        for plan in sheet.channels
        if plan.ownership is Ownership.HOST and plan.max_tolerance_seconds is None
    ]
    findings += [
        _hint("manual_task", f"manual {task.kind} {task.id} needs the user at {task.at}")
        for task in sheet.manual_tasks
    ]
    return findings


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


def _evidence_refs(sheet: RunSheet) -> Iterator[tuple[str, str | None]]:
    for timed in sheet.timed_actions:
        yield f"timed action {timed.id}", timed.evidence
    for rule in sheet.feedback_rules:
        yield f"feedback rule {rule.id}", rule.evidence
    for care in sheet.care_rules:
        for step in care.schedule:
            yield f"care step {step.id}", step.evidence


def check_evidence(run_sheet: RunSheet, cards: Mapping[str, EvidenceCard]) -> tuple[Finding, ...]:
    """Every set point must cite a card or user input; weak cards are flagged, never blocking.

    A card of any class, ``local`` included, is flagged until it is verified. ``verified`` comes
    from the cards the caller passes (the archive derives it from an operator's verification
    record), so the class a card names earns no exemption.
    """
    findings: list[Finding] = []
    for label, ref in _evidence_refs(run_sheet):
        if ref is not None and ref.startswith(USER_INPUT_PREFIX):
            continue
        card = cards.get(ref) if ref is not None else None
        if card is None:
            findings.append(_hint("no_evidence", f"{label}: no evidence card or user input"))
            continue
        if not card.verified:
            findings.append(
                _hint("unverified_source", f"{label}: card {card.id} is not verified; confirm it")
            )
        if not card.calibrated:
            findings.append(_hint("uncalibrated", f"{label}: card {card.id} is 未校准"))
    return tuple(findings)
