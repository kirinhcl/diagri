"""Pure feedback and protection rule evaluation (spec 7.4).

Durations and gaps are measured only on the monotonic timestamps carried by readings and passed in
as ``now_mono``; the wall clock (``Reading.at``) is never consulted, so an NTP step cannot fill or
clear a "for N seconds" condition.
"""

from collections.abc import Sequence

from growbridge.archive.models import (
    Channel,
    Condition,
    FeedbackRule,
    Model,
    ProtectionRule,
    RuleAction,
)
from growbridge.ports import Reading


class RuleState(Model):
    active: bool = False
    since: float | None = None  # monotonic start of the condition currently being timed
    last_switch: float | None = None  # monotonic time of the last action
    last_seen: float | None = None  # monotonic time of the last valid reading


class Decision(Model):
    rule_id: str
    action: RuleAction | None
    state: RuleState
    pause: bool = False
    reason: str


def valid_reading(
    reading: Reading | None, unit: str, validity_seconds: float, now_mono: float
) -> bool:
    """A reading may drive a rule only if present, valued, ok, in the rule's unit and fresh."""
    return (
        reading is not None
        and reading.value is not None
        and reading.quality == "ok"
        and reading.unit == unit
        and now_mono - reading.mono <= validity_seconds
    )


def _observe(state: RuleState, reading: Reading, max_gap_seconds: float) -> RuleState:
    """Record a valid reading; a gap longer than ``max_gap_seconds`` restarts the timing."""
    gap = None if state.last_seen is None else reading.mono - state.last_seen
    since = None if gap is not None and gap > max_gap_seconds else state.since
    return state.model_copy(update={"since": since, "last_seen": reading.mono})


def _timed(
    state: RuleState, holds: bool, reading: Reading, duration: float
) -> tuple[RuleState, bool]:
    """Start or clear the timer for ``holds``; report whether it has lasted ``duration``."""
    if not holds:
        return state.model_copy(update={"since": None}), False
    since = reading.mono if state.since is None else state.since
    return state.model_copy(update={"since": since}), reading.mono - since >= duration


def _switch_allowed(state: RuleState, now_mono: float, min_switch_seconds: float) -> bool:
    return state.last_switch is None or now_mono - state.last_switch >= min_switch_seconds


def _invalid(rule_id: str, state: RuleState, pause: bool, reason: str) -> Decision:
    cleared = state.model_copy(update={"since": None})
    return Decision(rule_id=rule_id, action=None, state=cleared, pause=pause, reason=reason)


def evaluate_feedback(
    rule: FeedbackRule,
    reading: Reading | None,
    state: RuleState,
    now_mono: float,
    max_gap_seconds: float,
) -> Decision:
    if reading is None or not valid_reading(reading, rule.unit, rule.validity_seconds, now_mono):
        pause = rule.on_missing == "pause"
        return _invalid(
            rule.id, state, pause, f"no valid {rule.sensor} reading ({rule.on_missing})"
        )
    value = reading.value
    assert value is not None  # guaranteed by valid_reading
    state = _observe(state, reading, max_gap_seconds)
    condition: Condition = rule.recover if state.active else rule.trigger
    state, lasted = _timed(state, condition.holds(value), reading, rule.duration_seconds)
    if not lasted or not _switch_allowed(state, now_mono, rule.min_switch_seconds):
        return Decision(rule_id=rule.id, action=None, state=state, reason="waiting")
    switched = state.model_copy(
        update={"active": not state.active, "since": None, "last_switch": now_mono}
    )
    if state.active:
        return Decision(rule_id=rule.id, action=rule.release, state=switched, reason="recovered")
    return Decision(rule_id=rule.id, action=rule.action, state=switched, reason="triggered")


def evaluate_protection(
    rule: ProtectionRule,
    reading: Reading | None,
    state: RuleState,
    now_mono: float,
    max_gap_seconds: float,
) -> Decision:
    """Protection acts for as long as the trigger keeps holding; it never pauses or releases."""
    if reading is None or not valid_reading(reading, rule.unit, rule.validity_seconds, now_mono):
        return _invalid(rule.id, state, False, f"no valid {rule.sensor} reading")
    value = reading.value
    assert value is not None  # guaranteed by valid_reading
    state = _observe(state, reading, max_gap_seconds)
    holds = rule.trigger.holds(value)
    state, lasted = _timed(state, holds, reading, rule.duration_seconds)
    if not holds:
        state = state.model_copy(update={"active": False})
    if not lasted:
        return Decision(rule_id=rule.id, action=None, state=state, reason="waiting")
    tripped = state.model_copy(update={"active": True, "last_switch": now_mono})
    return Decision(rule_id=rule.id, action=rule.action, state=tripped, reason="protecting")


def resolve(decisions: Sequence[tuple[FeedbackRule, Decision]]) -> dict[Channel, RuleAction]:
    """Per channel, keep the action of the highest-priority rule (earlier rule wins a tie)."""
    chosen: dict[Channel, tuple[int, RuleAction]] = {}
    for rule, decision in decisions:
        action = decision.action
        if action is None:
            continue
        current = chosen.get(action.channel)
        if current is None or rule.priority > current[0]:
            chosen[action.channel] = (rule.priority, action)
    return {channel: action for channel, (_, action) in chosen.items()}
