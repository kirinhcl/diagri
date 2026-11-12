import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from growbridge.archive.clock import SystemClock
from growbridge.archive.models import (
    LEVEL_RANGES,
    CareRule,
    Channel,
    ChannelPlan,
    Condition,
    Ownership,
    RuleAction,
    RunSheet,
    SafetyConfig,
    SamplingPlan,
    TimedAction,
    check_level,
    scheduled_level,
)
from growbridge.sim.clock import FakeClock
from growbridge.sim.fixtures import humidity_rule, make_run_sheet, make_safety
from growbridge.workflow import states

# Every kind of number a run sheet holds. NaN would be stored as null and could not be read back,
# and a NaN threshold never compares true, so a rule holding it would never act.
FLOAT_PATHS = (
    "duration_seconds",
    "max_wait_seconds",
    "sampling.interval_seconds",
    "sampling.max_gap_seconds",
    "channels.0.max_tolerance_seconds",
    "feedback_rules.0.trigger.value",
    "feedback_rules.0.recover.value",
    "feedback_rules.0.validity_seconds",
    "feedback_rules.0.duration_seconds",
    "feedback_rules.0.min_switch_seconds",
)
NOT_FINITE = (float("nan"), float("inf"), float("-inf"), "nan", "Infinity", "-inf")
# The same holds for a protection rule: with a NaN threshold it would never act.
SAFETY_FLOAT_PATHS = (
    "rules.0.trigger.value",
    "rules.0.validity_seconds",
    "rules.0.duration_seconds",
    "approved_at",
)


def at(hour, minute=0, zone="Europe/Helsinki"):
    return datetime(2026, 11, 9, hour, minute, tzinfo=ZoneInfo(zone)).timestamp()


def test_models_are_frozen_and_reject_unknown_fields():
    action = RuleAction(channel=Channel.LIGHT, level=40)

    with pytest.raises(ValidationError):
        action.level = 50
    with pytest.raises(ValidationError):
        RuleAction(channel=Channel.LIGHT, level=40, role="operator")


@pytest.mark.parametrize(
    ("channel", "level"),
    [(Channel.LIGHT, 101), (Channel.EXHAUST, -1), (Channel.FAN, 11), (Channel.PUMP, 2)],
)
def test_levels_outside_the_device_range_are_rejected(channel, level):
    with pytest.raises(ValueError):
        check_level(channel, level)
    with pytest.raises(ValidationError):
        RuleAction(channel=channel, level=level)


def test_level_ranges_cover_every_channel():
    assert set(LEVEL_RANGES) == set(Channel)
    assert check_level(Channel.FAN, 10) == 10


@pytest.mark.parametrize("value", ["24:00", "7:30", "12:60", "noon"])
def test_timed_action_rejects_malformed_time(value):
    with pytest.raises(ValidationError):
        TimedAction(id="t", channel=Channel.LIGHT, at=value, level=10)


@pytest.mark.parametrize(
    ("op", "reading", "expected"),
    [(">", 28.0, False), (">=", 28.0, True), ("<", 27.9, True), ("<=", 28.1, False)],
)
def test_condition_compares_against_its_value(op, reading, expected):
    assert Condition(op=op, value=28.0).holds(reading) is expected


def test_scheduled_level_uses_latest_action_and_wraps_past_midnight():
    actions = (
        TimedAction(id="on", channel=Channel.LIGHT, at="06:00", level=60),
        TimedAction(id="off", channel=Channel.LIGHT, at="22:00", level=0),
    )

    assert scheduled_level(actions, 6 * 60) == 60
    assert scheduled_level(actions, 21 * 60 + 59) == 60
    assert scheduled_level(actions, 23 * 60) == 0
    assert scheduled_level(actions, 5 * 60) == 0
    assert scheduled_level((), 5 * 60) is None


def test_run_sheet_expected_levels_follow_the_project_timezone():
    sheet = make_run_sheet()

    assert sheet.expected_levels(at(12)) == {Channel.LIGHT: 60, Channel.EXHAUST: 30}
    assert sheet.expected_levels(at(23)) == {Channel.LIGHT: 0, Channel.EXHAUST: 30}
    assert sheet.local_minute(at(6, 30)) == 6 * 60 + 30


def test_run_sheet_never_expects_a_level_on_a_device_managed_channel():
    base = make_run_sheet()
    sheet = base.model_copy(
        update={
            "channels": tuple(
                plan.model_copy(update={"ownership": Ownership.DEVICE})
                if plan.channel is Channel.LIGHT
                else plan
                for plan in base.channels
            )
        }
    )

    assert Channel.LIGHT not in sheet.expected_levels(at(12))
    assert Channel.LIGHT not in sheet.host_channels()
    assert sheet.plan(Channel.LIGHT).ownership is Ownership.DEVICE


def test_run_sheet_care_levels_come_from_care_rules():
    care = CareRule(
        id="care-light",
        channel=Channel.LIGHT,
        schedule=(
            TimedAction(id="c-on", channel=Channel.LIGHT, at="08:00", level=30),
            TimedAction(id="c-off", channel=Channel.LIGHT, at="20:00", level=0),
        ),
    )
    sheet = make_run_sheet().model_copy(update={"care_rules": (care,)})

    assert sheet.care_levels(at(9)) == {Channel.LIGHT: 30}
    assert sheet.care_levels(at(21)) == {Channel.LIGHT: 0}


def test_run_sheet_rejects_duplicate_channels_and_unknown_timezone():
    plan = ChannelPlan(channel=Channel.LIGHT, ownership=Ownership.HOST)
    fields = make_run_sheet().model_dump()

    with pytest.raises(ValidationError):
        RunSheet(**{**fields, "channels": (plan, plan)})
    with pytest.raises(ValidationError):
        RunSheet(**{**fields, "timezone": "Mars/Olympus"})


def put(data: dict, path: str, value) -> dict:
    """Set the field at a dotted path such as ``feedback_rules.0.trigger.value``."""
    *parents, last = path.split(".")
    node = data
    for key in parents:
        node = node[int(key)] if key.isdigit() else node[key]
    node[int(last) if last.isdigit() else last] = value
    return data


def sheet_data() -> dict:
    return make_run_sheet(feedback_rules=(humidity_rule(),)).model_dump(mode="json")


@pytest.mark.parametrize("path", FLOAT_PATHS)
def test_run_sheet_rejects_a_number_that_is_not_finite_and_says_where(path):
    with pytest.raises(ValidationError, match=re.escape(path)):
        RunSheet.model_validate(put(sheet_data(), path, float("nan")))


@pytest.mark.parametrize("value", NOT_FINITE)
def test_run_sheet_rejects_every_spelling_of_nan_and_infinity(value):
    with pytest.raises(ValidationError):
        RunSheet.model_validate(put(sheet_data(), "feedback_rules.0.trigger.value", value))


def test_a_run_sheet_reads_back_from_storage_unchanged():
    sheet = RunSheet.model_validate(sheet_data())

    assert RunSheet.model_validate_json(sheet.model_dump_json()) == sheet


def safety_data() -> dict:
    return make_safety(approved_by="op-1", approved_at=1.0).model_dump(mode="json")


@pytest.mark.parametrize("path", SAFETY_FLOAT_PATHS)
def test_safety_config_rejects_a_number_that_is_not_finite_and_says_where(path):
    with pytest.raises(ValidationError, match=re.escape(path)):
        SafetyConfig.model_validate(put(safety_data(), path, float("nan")))


@pytest.mark.parametrize("value", NOT_FINITE)
def test_safety_config_rejects_every_spelling_of_nan_and_infinity(value):
    with pytest.raises(ValidationError):
        SafetyConfig.model_validate(put(safety_data(), "rules.0.trigger.value", value))


def test_a_safety_config_reads_back_from_storage_unchanged():
    config = SafetyConfig.model_validate(safety_data())

    assert SafetyConfig.model_validate_json(config.model_dump_json()) == config


def test_digest_is_stable_and_changes_with_content():
    sheet = make_run_sheet()
    sampling = SamplingPlan(interval_seconds=5, max_gap_seconds=60)
    changed = sheet.model_copy(update={"sampling": sampling})

    assert sheet.digest() == make_run_sheet().digest()
    assert sheet.digest() != changed.digest()


def test_every_state_has_a_chinese_label_and_terminal_sets_are_final():
    for enum in (states.RoundState, states.StageState, states.TaskState):
        assert all(member in states.LABELS for member in enum)

    assert states.LABELS[states.StageState.RECOVERY_CHECK] == "恢复待核对"
    assert states.STAGE_TERMINAL == {states.StageState.ENDED, states.StageState.STOPPED}
    assert states.ROUND_TERMINAL == {states.RoundState.DELIVERED, states.RoundState.ABORTED}
    assert states.TASK_TERMINAL == {states.TaskState.DONE, states.TaskState.ENDED}


def test_fake_clock_separates_wall_jumps_from_elapsed_time():
    clock = FakeClock()
    wall, mono = clock.now(), clock.monotonic()

    clock.advance(30)
    clock.jump(3600)

    assert clock.now() == wall + 3630
    assert clock.monotonic() == mono + 30
    assert clock.synced is True


def test_system_clock_reports_real_time_and_sync_flag():
    clock = SystemClock(synced=False)

    assert clock.now() > 1_700_000_000
    assert clock.monotonic() <= clock.monotonic()
    assert clock.synced is False
