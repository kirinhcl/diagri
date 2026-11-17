from growbridge.archive.models import (
    LEVEL_RANGES,
    CareRule,
    Channel,
    ChannelPlan,
    Condition,
    ManualTask,
    Ownership,
    ProtectionRule,
    RuleAction,
    SamplingPlan,
    TimedAction,
)
from growbridge.planning.validate import validate_run_sheet
from growbridge.ports import Capabilities
from growbridge.sim.fixtures import humidity_rule, make_run_sheet, make_safety
from growbridge.vocab import load_catalog, packaged_text

CAPS = Capabilities(
    version="test",
    sensors={"humi": "%", "temp": "C"},
    level_ranges=dict(LEVEL_RANGES),
    outlets={},
)


def codes(findings, *, blocking=None):
    return [f.code for f in findings if blocking is None or f.blocking is blocking]


def sheet_with_plan(channel, **plan):
    base = make_run_sheet()
    others = tuple(p for p in base.channels if p.channel is not channel)
    return base.model_copy(update={"channels": (*others, ChannelPlan(channel=channel, **plan))})


def test_default_run_sheet_has_no_blocking_findings():
    findings = validate_run_sheet(make_run_sheet(), CAPS, make_safety())
    assert codes(findings, blocking=True) == []


def test_default_run_sheet_reports_missing_tolerance_as_hint():
    findings = validate_run_sheet(make_run_sheet(), CAPS)
    assert "missing_tolerance" in codes(findings, blocking=False)


def test_valid_feedback_rule_passes():
    sheet = make_run_sheet(feedback_rules=(humidity_rule(),))
    assert codes(validate_run_sheet(sheet, CAPS), blocking=True) == []


def test_unknown_sensor_blocks():
    sheet = make_run_sheet(feedback_rules=(humidity_rule(sensor="co2"),))
    assert "unknown_sensor" in codes(validate_run_sheet(sheet, CAPS), blocking=True)


def test_unit_mismatch_blocks():
    sheet = make_run_sheet(feedback_rules=(humidity_rule(unit="C"),))
    assert "unit_mismatch" in codes(validate_run_sheet(sheet, CAPS), blocking=True)


def test_safety_rule_with_unknown_sensor_or_unit_blocks():
    rule = make_safety().rules[0]
    bad_sensor = make_safety(rules=(rule.model_copy(update={"sensor": "co2"}),))
    bad_unit = make_safety(rules=(rule.model_copy(update={"unit": "F"}),))
    assert "unknown_sensor" in codes(validate_run_sheet(make_run_sheet(), CAPS, bad_sensor))
    assert "unit_mismatch" in codes(validate_run_sheet(make_run_sheet(), CAPS, bad_unit))


def test_planning_action_on_device_managed_channel_blocks():
    sheet = sheet_with_plan(Channel.LIGHT, ownership=Ownership.DEVICE)
    findings = validate_run_sheet(sheet, CAPS)
    assert "device_owned_write" in codes(findings, blocking=True)


def test_device_owned_channel_without_actions_is_fine():
    sheet = sheet_with_plan(Channel.FAN, ownership=Ownership.DEVICE)
    assert "device_owned_write" not in codes(validate_run_sheet(sheet, CAPS))


def test_pump_owned_by_device_blocks():
    sheet = sheet_with_plan(Channel.PUMP, ownership=Ownership.DEVICE)
    assert "pump_device_owned" in codes(validate_run_sheet(sheet, CAPS), blocking=True)


def test_other_device_owned_channels_do_not_trip_the_pump_check():
    sheet = sheet_with_plan(Channel.FAN, ownership=Ownership.DEVICE)
    assert "pump_device_owned" not in codes(validate_run_sheet(sheet, CAPS))


def test_host_owned_pump_does_not_trip_the_pump_check():
    sheet = sheet_with_plan(Channel.PUMP, ownership=Ownership.HOST)
    assert "pump_device_owned" not in codes(validate_run_sheet(sheet, CAPS))


def test_sheet_without_a_pump_plan_blocks():
    base = make_run_sheet()
    channels = tuple(plan for plan in base.channels if plan.channel is not Channel.PUMP)
    sheet = base.model_copy(update={"channels": channels})
    assert "pump_device_owned" in codes(validate_run_sheet(sheet, CAPS), blocking=True)


def test_feedback_action_on_device_channel_blocks():
    sheet = sheet_with_plan(Channel.EXHAUST, ownership=Ownership.DEVICE).model_copy(
        update={"feedback_rules": (humidity_rule(),)}
    )
    assert "device_owned_write" in codes(validate_run_sheet(sheet, CAPS), blocking=True)


def test_action_on_channel_missing_from_plan_blocks():
    base = make_run_sheet()
    channels = tuple(p for p in base.channels if p.channel is not Channel.LIGHT)
    sheet = base.model_copy(update={"channels": channels})
    assert "device_owned_write" in codes(validate_run_sheet(sheet, CAPS), blocking=True)


def test_planning_pump_start_blocks():
    pump_on = TimedAction(id="pump-on", channel=Channel.PUMP, at="08:00", level=1)
    sheet = make_run_sheet(timed_actions=(*make_run_sheet().timed_actions, pump_on))
    assert "pump_action" in codes(validate_run_sheet(sheet, CAPS), blocking=True)


def test_pump_start_via_feedback_end_care_or_safety_blocks():
    pump = RuleAction(channel=Channel.PUMP, level=1)
    feedback = make_run_sheet(feedback_rules=(humidity_rule(action=pump, release=None),))
    ending = make_run_sheet(end_actions=(pump,))
    care = make_run_sheet(
        care_rules=(
            CareRule(
                id="care",
                channel=Channel.PUMP,
                schedule=(TimedAction(id="c1", channel=Channel.PUMP, at="01:00", level=1),),
            ),
        )
    )
    protection = ProtectionRule(
        id="p",
        sensor="temp",
        unit="C",
        validity_seconds=20,
        trigger=Condition(op=">", value=35),
        duration_seconds=30,
        action=pump,
    )
    for sheet, safety in (
        (feedback, None),
        (ending, None),
        (care, None),
        (make_run_sheet(), make_safety(rules=(protection,))),
    ):
        assert "pump_action" in codes(validate_run_sheet(sheet, CAPS, safety), blocking=True)


def test_pump_off_is_allowed():
    off = TimedAction(id="pump-off", channel=Channel.PUMP, at="08:00", level=0)
    sheet = make_run_sheet(timed_actions=(*make_run_sheet().timed_actions, off))
    assert "pump_action" not in codes(validate_run_sheet(sheet, CAPS))


def test_humidity_feedback_changing_light_is_blocked():
    rule = humidity_rule(action=RuleAction(channel=Channel.LIGHT, level=20), release=None)
    sheet = make_run_sheet(feedback_rules=(rule,))
    assert "humidity_exhaust_only" in codes(validate_run_sheet(sheet, CAPS), blocking=True)


def test_humidity_feedback_release_on_other_channel_is_blocked():
    rule = humidity_rule(release=RuleAction(channel=Channel.FAN, level=1))
    sheet = make_run_sheet(feedback_rules=(rule,))
    assert "humidity_exhaust_only" in codes(validate_run_sheet(sheet, CAPS), blocking=True)


MOIST = load_catalog(
    packaged_text()
    + """
[[variable]]
id = "leaf_air_moisture"
kind = "sensor"
label_en = "Leaf air moisture"
label_zh = "叶面空气湿度"
quantity = "relative_humidity"
unit = "%"
aliases = ["moist"]
"""
)


def _light_rule(sensor):
    return humidity_rule(
        sensor=sensor, action=RuleAction(channel=Channel.LIGHT, level=20), release=None
    )


def test_catalog_humidity_name_is_exhaust_only():
    sheet = make_run_sheet(feedback_rules=(_light_rule("moist"),))
    assert "humidity_exhaust_only" in codes(
        validate_run_sheet(sheet, CAPS, catalog=MOIST), blocking=True
    )


def test_substring_rule_still_blocks_unknown_names():
    sheet = make_run_sheet(feedback_rules=(_light_rule("rh"),))
    assert "humidity_exhaust_only" in codes(validate_run_sheet(sheet, CAPS), blocking=True)


def test_catalog_never_unblocks():
    sheet = make_run_sheet(feedback_rules=(_light_rule("humi"),))
    assert "humidity_exhaust_only" in codes(validate_run_sheet(sheet, CAPS), blocking=True)
    assert "humidity_exhaust_only" in codes(
        validate_run_sheet(sheet, CAPS, catalog=MOIST), blocking=True
    )


def test_temperature_feedback_may_change_light():
    rule = humidity_rule(
        id="t",
        sensor="temp",
        unit="C",
        action=RuleAction(channel=Channel.LIGHT, level=30),
        release=RuleAction(channel=Channel.LIGHT, level=60),
    )
    sheet = make_run_sheet(feedback_rules=(rule,))
    assert "humidity_exhaust_only" not in codes(validate_run_sheet(sheet, CAPS))


def test_same_channel_same_priority_different_level_is_conflict():
    a = humidity_rule(id="a")
    b = humidity_rule(id="b", action=RuleAction(channel=Channel.EXHAUST, level=60))
    sheet = make_run_sheet(feedback_rules=(a, b))
    assert "rule_conflict" in codes(validate_run_sheet(sheet, CAPS), blocking=True)


def test_conflict_resolved_by_priority_or_equal_level():
    a = humidity_rule(id="a", priority=1)
    b = humidity_rule(id="b", action=RuleAction(channel=Channel.EXHAUST, level=60))
    same = humidity_rule(id="c")
    by_priority = make_run_sheet(feedback_rules=(a, b))
    equal_level = make_run_sheet(feedback_rules=(humidity_rule(id="a"), same))
    assert "rule_conflict" not in codes(validate_run_sheet(by_priority, CAPS))
    assert "rule_conflict" not in codes(validate_run_sheet(equal_level, CAPS))


def test_feedback_overlapping_protection_with_other_level_is_safety_conflict():
    rule = humidity_rule(
        id="warm",
        sensor="temp",
        unit="C",
        trigger=Condition(op=">", value=30),
        recover=Condition(op="<", value=25),
        action=RuleAction(channel=Channel.LIGHT, level=80),
        release=None,
    )
    sheet = make_run_sheet(feedback_rules=(rule,))
    findings = validate_run_sheet(sheet, CAPS, make_safety())
    assert "safety_conflict" in codes(findings, blocking=True)


def test_feedback_with_disjoint_range_from_protection_is_not_conflict():
    rule = humidity_rule(
        id="cool",
        sensor="temp",
        unit="C",
        trigger=Condition(op="<", value=20),
        recover=Condition(op=">", value=24),
        action=RuleAction(channel=Channel.LIGHT, level=80),
        release=None,
    )
    sheet = make_run_sheet(feedback_rules=(rule,))
    assert "safety_conflict" not in codes(validate_run_sheet(sheet, CAPS, make_safety()))


def test_sampling_problems_block():
    for plan in (
        SamplingPlan(interval_seconds=0, max_gap_seconds=120),
        SamplingPlan(interval_seconds=60, max_gap_seconds=30),
    ):
        sheet = make_run_sheet(sampling=plan)
        assert "sampling" in codes(validate_run_sheet(sheet, CAPS), blocking=True)


def test_rule_validity_shorter_than_sampling_interval_blocks():
    sheet = make_run_sheet(
        sampling=SamplingPlan(interval_seconds=60, max_gap_seconds=300),
        feedback_rules=(humidity_rule(validity_seconds=20),),
    )
    assert "sampling" in codes(validate_run_sheet(sheet, CAPS), blocking=True)


def test_non_positive_duration_blocks():
    sheet = make_run_sheet(duration_seconds=0)
    assert "duration" in codes(validate_run_sheet(sheet, CAPS), blocking=True)


def test_non_positive_rule_duration_blocks():
    sheet = make_run_sheet(feedback_rules=(humidity_rule(duration_seconds=0),))
    assert "duration" in codes(validate_run_sheet(sheet, CAPS), blocking=True)


def test_non_positive_wait_blocks():
    sheet = make_run_sheet(max_wait_seconds=0)
    assert "wait" in codes(validate_run_sheet(sheet, CAPS), blocking=True)


def test_manual_task_is_a_hint_not_a_block():
    task = ManualTask(id="water", kind="irrigation", at="09:00")
    findings = validate_run_sheet(make_run_sheet(manual_tasks=(task,)), CAPS)
    manual = [f for f in findings if f.code == "manual_task"]
    assert len(manual) == 1
    assert manual[0].blocking is False
    assert "water" in manual[0].message


def test_tolerance_given_removes_hint_for_that_channel():
    base = make_run_sheet()
    channels = tuple(p.model_copy(update={"max_tolerance_seconds": 600}) for p in base.channels)
    findings = validate_run_sheet(base.model_copy(update={"channels": channels}), CAPS)
    assert "missing_tolerance" not in codes(findings)


def test_level_outside_device_range_blocks():
    narrow = CAPS.model_copy(update={"level_ranges": {**CAPS.level_ranges, Channel.LIGHT: (0, 50)}})
    findings = validate_run_sheet(make_run_sheet(), narrow)
    assert "level_range" in codes(findings, blocking=True)


def test_validation_does_not_mutate_inputs():
    sheet = make_run_sheet(feedback_rules=(humidity_rule(),))
    before = sheet.digest()
    validate_run_sheet(sheet, CAPS, make_safety())
    assert sheet.digest() == before
