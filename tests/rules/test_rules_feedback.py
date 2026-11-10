from growbridge.archive.models import Channel, Condition, RuleAction
from growbridge.executor.rules import (
    Decision,
    RuleState,
    evaluate_feedback,
    resolve,
    valid_reading,
)
from growbridge.ports import Reading
from growbridge.sim.fixtures import humidity_rule

GAP = 120.0


def reading(value, mono, *, at=None, quality="ok", unit="%", sensor="humi"):
    return Reading(
        sensor=sensor,
        value=value,
        unit=unit,
        at=mono if at is None else at,
        mono=mono,
        quality=quality,
    )


def run(rule, samples, state=None, *, gap=GAP):
    """Feed (value, mono) samples one by one; return the last decision and every action."""
    state = state or RuleState()
    decision = None
    actions = []
    for value, mono in samples:
        decision = evaluate_feedback(rule, reading(value, mono), state, mono, gap)
        state = decision.state
        if decision.action is not None:
            actions.append((mono, decision.action))
    return decision, actions


def ramp(value, start, stop, step=1):
    return [(float(value), float(t)) for t in range(start, stop + 1, step)]


# --- valid_reading ------------------------------------------------------------------------------


def test_valid_reading_accepts_fresh_ok_reading():
    assert valid_reading(reading(75, 100), "%", 20, 110)


def test_valid_reading_rejects_missing_reading_and_value():
    assert not valid_reading(None, "%", 20, 110)
    assert not valid_reading(reading(None, 100), "%", 20, 110)


def test_valid_reading_rejects_bad_quality_unit_and_stale():
    assert not valid_reading(reading(75, 100, quality="suspect"), "%", 20, 110)
    assert not valid_reading(reading(75, 100, quality="invalid"), "%", 20, 110)
    assert not valid_reading(reading(75, 100, unit="C"), "%", 20, 110)
    assert not valid_reading(reading(75, 100), "%", 20, 121)


def test_valid_reading_boundary_age_is_still_valid():
    assert valid_reading(reading(75, 100), "%", 20, 120)


# --- evaluate_feedback --------------------------------------------------------------------------


def test_feedback_fires_only_after_full_duration():
    rule = humidity_rule()
    decision, actions = run(rule, ramp(80, 0, 59))
    assert actions == []
    assert decision.action is None
    decision, actions = run(rule, ramp(80, 0, 60))
    assert [a for _, a in actions] == [RuleAction(channel=Channel.EXHAUST, level=80)]
    assert decision.state.active is True


def test_feedback_condition_dropping_out_resets_timer():
    rule = humidity_rule()
    samples = ramp(80, 0, 40) + [(65.0, 41.0)] + ramp(80, 42, 120)
    _, actions = run(rule, samples)
    assert actions[0][0] == 102.0  # 42 + 60, not 60


def test_feedback_releases_after_recover_condition_holds_for_duration():
    rule = humidity_rule(min_switch_seconds=0)
    _, actions = run(rule, ramp(80, 0, 60) + ramp(55, 61, 130))
    assert [(t, a.level) for t, a in actions] == [(60.0, 80), (121.0, 30)]


def test_feedback_hysteresis_band_neither_releases_nor_retriggers():
    rule = humidity_rule(min_switch_seconds=0)
    decision, actions = run(rule, ramp(80, 0, 60) + ramp(65, 61, 300))
    assert len(actions) == 1
    assert decision.state.active is True


def test_feedback_min_switch_delays_release():
    rule = humidity_rule(min_switch_seconds=120)
    _, actions = run(rule, ramp(80, 0, 60) + ramp(55, 61, 200))
    assert [(t, a.level) for t, a in actions] == [(60.0, 80), (180.0, 30)]


def test_feedback_min_switch_delays_retrigger():
    rule = humidity_rule(min_switch_seconds=100)
    samples = ramp(80, 0, 60) + ramp(55, 61, 160) + ramp(80, 161, 400)
    _, actions = run(rule, samples)
    assert [(t, a.level) for t, a in actions] == [(60.0, 80), (160.0, 30), (260.0, 80)]


def test_feedback_release_without_release_action_only_deactivates():
    rule = humidity_rule(release=None, min_switch_seconds=0)
    decision, actions = run(rule, ramp(80, 0, 60) + ramp(55, 61, 121))
    assert len(actions) == 1
    assert decision.action is None
    assert decision.state.active is False


def test_feedback_missing_reading_hold_keeps_state_and_clears_timer():
    rule = humidity_rule()
    state = run(rule, ramp(80, 0, 40))[0].state
    decision = evaluate_feedback(rule, None, state, 41.0, GAP)
    assert decision.action is None
    assert decision.pause is False
    assert decision.state.since is None
    _, actions = run(rule, ramp(80, 42, 120), decision.state)
    assert actions[0][0] == 102.0


def test_feedback_missing_reading_hold_keeps_active_rule_active():
    rule = humidity_rule()
    state = run(rule, ramp(80, 0, 60))[0].state
    decision = evaluate_feedback(rule, None, state, 70.0, GAP)
    assert decision.state.active is True
    assert decision.action is None


def test_feedback_missing_reading_pause_requests_pause():
    rule = humidity_rule(on_missing="pause")
    decision = evaluate_feedback(rule, None, RuleState(), 10.0, GAP)
    assert decision.pause is True
    assert decision.action is None


def test_feedback_field_without_value_is_treated_as_missing():
    rule = humidity_rule(on_missing="pause")
    decision = evaluate_feedback(rule, reading(None, 10), RuleState(), 10.0, GAP)
    assert decision.pause is True


def test_feedback_stale_or_wrong_unit_or_suspect_reading_never_triggers():
    rule = humidity_rule()
    state = RuleState()
    for bad in (
        reading(90, 0, quality="suspect"),
        reading(90, 0, unit="C"),
        reading(90, 0, quality="invalid"),
    ):
        assert evaluate_feedback(rule, bad, state, 5.0, GAP).action is None
    stale = evaluate_feedback(rule, reading(90, 0), state, 500.0, GAP)
    assert stale.action is None


def test_rules_gap_breaks_continuity():
    rule = humidity_rule(validity_seconds=500)
    # 40 s of high humidity, then silence until t=200 (gap 160 > 120), then a high reading.
    state = run(rule, ramp(80, 0, 40))[0].state
    decision = evaluate_feedback(rule, reading(80, 200), state, 200.0, GAP)
    assert decision.action is None
    assert decision.state.since == 200.0
    # the 40 s before the gap are not credited: 59 s after the gap is still not enough
    decision, actions = run(rule, ramp(80, 201, 259), decision.state)
    assert actions == []
    _, actions = run(rule, ramp(80, 260, 260), decision.state)
    assert len(actions) == 1


def test_feedback_gap_within_limit_keeps_continuity():
    rule = humidity_rule(validity_seconds=500)
    samples = ramp(80, 0, 30) + [(80.0, 90.0), (80.0, 100.0)]
    _, actions = run(rule, samples)
    assert [t for t, _ in actions] == [90.0]


def test_rules_duration_ignores_wall_clock_jump():
    rule = humidity_rule()
    state = RuleState()
    fired = []
    for mono in range(0, 61):
        # the wall clock leaps forward an hour at mono=30 (NTP step); monotonic is unaffected
        wall = 5000.0 + mono + (3600.0 if mono >= 30 else 0.0)
        decision = evaluate_feedback(
            rule, reading(80, float(mono), at=wall), state, float(mono), GAP
        )
        state = decision.state
        if decision.action is not None:
            fired.append(mono)
    assert fired == [60]


def test_rules_duration_not_cleared_by_backward_wall_clock_jump():
    rule = humidity_rule()
    state = RuleState()
    fired = []
    for mono in range(0, 61):
        wall = 90000.0 - (50000.0 if mono >= 20 else 0.0) + mono
        decision = evaluate_feedback(
            rule, reading(80, float(mono), at=wall), state, float(mono), GAP
        )
        state = decision.state
        if decision.action is not None:
            fired.append(mono)
    assert fired == [60]


def test_feedback_does_not_mutate_input_state():
    rule = humidity_rule()
    state = RuleState()
    evaluate_feedback(rule, reading(80, 0), state, 0.0, GAP)
    assert state == RuleState()


def test_condition_boundary_values_follow_operator():
    rule = humidity_rule(trigger=Condition(op=">=", value=70))
    _, actions = run(rule, ramp(70, 0, 60))
    assert len(actions) == 1


# --- resolve ------------------------------------------------------------------------------------


def _decision(rule, level):
    action = RuleAction(channel=rule.action.channel, level=level)
    return Decision(rule_id=rule.id, action=action, state=RuleState(), reason="test")


def test_resolve_takes_highest_priority_per_channel():
    low = humidity_rule(id="low", priority=1)
    high = humidity_rule(id="high", priority=5)
    result = resolve([(low, _decision(low, 40)), (high, _decision(high, 90))])
    assert result == {Channel.EXHAUST: RuleAction(channel=Channel.EXHAUST, level=90)}


def test_resolve_keeps_channels_separate_and_skips_idle_rules():
    exhaust = humidity_rule(id="e")
    fan = humidity_rule(id="f", action=RuleAction(channel=Channel.FAN, level=5))
    idle = humidity_rule(id="idle", priority=9)
    idle_decision = Decision(rule_id="idle", action=None, state=RuleState(), reason="idle")
    result = resolve(
        [(exhaust, _decision(exhaust, 70)), (fan, _decision(fan, 5)), (idle, idle_decision)]
    )
    assert result[Channel.EXHAUST].level == 70
    assert result[Channel.FAN].level == 5


def test_resolve_empty_returns_empty():
    assert resolve([]) == {}
