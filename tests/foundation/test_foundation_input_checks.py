"""Checks a safety configuration and a run sheet pass only when they come in (the batch 3
follow-up): a repeated id, a negative rule time and a retained level outside its channel's range.
A record read back from storage (validation context ``STORED``) still loads when it breaks one,
because raw records are never rewritten."""

import pytest
from pydantic import ValidationError

from growbridge.archive.models import (
    LEVEL_RANGES,
    STORED,
    CareRule,
    Channel,
    ChannelPlan,
    ManualTask,
    Ownership,
    ProtectionRule,
    RuleAction,
    RunSheet,
    SafetyConfig,
    TimedAction,
)
from growbridge.sim.fixtures import humidity_rule, make_run_sheet, make_safety


def problems(model, data) -> list[dict]:
    with pytest.raises(ValidationError) as caught:
        model.model_validate(data)
    return [
        {key: error[key] for key in ("type", "loc", "input", "ctx") if key in error}
        for error in caught.value.errors()
    ]


def safety_with_rules(*ids: str) -> dict:
    rule = make_safety().rules[0].model_dump(mode="json")
    return {**make_safety().model_dump(mode="json"), "rules": [{**rule, "id": i} for i in ids]}


# --- safety configuration: repeated rule ids -----------------------------------------------------


def test_a_rule_id_given_again_is_refused_at_the_repeat():
    found = problems(SafetyConfig, safety_with_rules("overheat", "dry-air", "overheat"))

    assert found == [
        {
            "type": "duplicate",
            "loc": ("rules", 2, "id"),
            "input": "overheat",
            "ctx": {"value": "overheat"},
        }
    ]


def test_every_repeat_of_a_rule_id_is_named():
    found = problems(SafetyConfig, safety_with_rules("a", "a", "b", "a", "b"))

    assert [error["loc"] for error in found] == [
        ("rules", 1, "id"),
        ("rules", 3, "id"),
        ("rules", 4, "id"),
    ]


def test_distinct_rule_ids_are_accepted():
    config = SafetyConfig.model_validate(safety_with_rules("overheat", "dry-air"))

    assert [rule.id for rule in config.rules] == ["overheat", "dry-air"]


# --- safety configuration: negative rule times ---------------------------------------------------


@pytest.mark.parametrize("field", ["validity_seconds", "duration_seconds"])
def test_a_negative_rule_time_is_refused_beside_its_field(field):
    data = safety_with_rules("overheat")
    data["rules"][0][field] = -1

    assert problems(SafetyConfig, data) == [
        {"type": "greater_than_equal", "loc": ("rules", 0, field), "input": -1.0, "ctx": {"ge": 0}}
    ]


@pytest.mark.parametrize("field", ["validity_seconds", "duration_seconds"])
def test_a_zero_rule_time_is_accepted_as_the_console_allows_it(field):
    data = safety_with_rules("overheat")
    data["rules"][0][field] = 0

    assert getattr(SafetyConfig.model_validate(data).rules[0], field) == 0


def test_a_protection_rule_built_directly_is_checked_too():
    rule = make_safety().rules[0].model_dump()

    with pytest.raises(ValidationError):
        ProtectionRule(**{**rule, "duration_seconds": -0.5})


# --- run sheet: repeated row ids -----------------------------------------------------------------


def _timed(id_: str) -> dict:
    return TimedAction(id=id_, channel=Channel.LIGHT, at="06:00", level=50).model_dump(mode="json")


def _task(id_: str) -> dict:
    return ManualTask(id=id_, kind="photo", at="09:00").model_dump(mode="json")


def _end(channel: Channel) -> dict:
    return RuleAction(channel=channel, level=0).model_dump(mode="json")


def _feedback(id_: str) -> dict:
    return humidity_rule(id=id_).model_dump(mode="json")


def _step(id_: str, hour: int) -> TimedAction:
    return TimedAction(id=id_, channel=Channel.FAN, at=f"{hour:02d}:00", level=1)


def _care(id_: str, *steps: str) -> dict:
    """A fan care rule as sent, a step per name in ``steps`` an hour apart. It is built as data,
    not as a model, because some tests send a step name twice."""
    names = steps or ("on",)
    schedule = [_step(name, 8 + hour).model_dump(mode="json") for hour, name in enumerate(names)]
    return {"id": id_, "channel": Channel.FAN.value, "schedule": schedule}


ROWS = {
    "timed_actions": ([_timed("on"), _timed("off"), _timed("on")], "id", "on"),
    "manual_tasks": ([_task("photo"), _task("photo")], "id", "photo"),
    # an end action has no id: its channel names it ("end:<channel>" in the action records)
    "end_actions": (
        [_end(Channel.LIGHT), _end(Channel.FAN), _end(Channel.LIGHT)],
        "channel",
        "light",
    ),
    "feedback_rules": ([_feedback("humid"), _feedback("dry"), _feedback("humid")], "id", "humid"),
    "care_rules": ([_care("care-fan"), _care("care-fan")], "id", "care-fan"),
}


@pytest.mark.parametrize("name", sorted(ROWS))
def test_a_repeated_row_is_refused_at_the_repeat(name):
    rows, key, value = ROWS[name]
    data = {**make_run_sheet().model_dump(mode="json"), name: rows}

    found = problems(RunSheet, data)

    assert found == [
        {
            "type": "duplicate",
            "loc": (name, len(rows) - 1, key),
            "input": value,
            "ctx": {"value": value},
        }
    ]


def test_the_same_name_in_two_different_lists_is_accepted():
    data = {
        **make_run_sheet().model_dump(mode="json"),
        "timed_actions": [_timed("morning")],
        "manual_tasks": [_task("morning")],
    }

    assert RunSheet.model_validate(data).manual_tasks[0].id == "morning"


def test_a_step_id_repeated_inside_one_care_schedule_is_refused_at_the_repeat():
    data = {
        **make_run_sheet().model_dump(mode="json"),
        "care_rules": [_care("care-fan", "on", "off", "on")],
    }

    assert problems(RunSheet, data) == [
        {
            "type": "duplicate",
            "loc": ("care_rules", 0, "schedule", 2, "id"),
            "input": "on",
            "ctx": {"value": "on"},
        }
    ]


def test_distinct_feedback_care_and_step_ids_are_accepted():
    data = {
        **make_run_sheet().model_dump(mode="json"),
        "feedback_rules": [_feedback("humid"), _feedback("dry")],
        "care_rules": [_care("care-fan", "on", "off"), _care("care-fan-2", "low")],
    }

    sheet = RunSheet.model_validate(data)

    assert [rule.id for rule in sheet.feedback_rules] == ["humid", "dry"]
    assert [step.id for step in sheet.care_rules[0].schedule] == ["on", "off"]


def test_a_care_rule_built_directly_is_checked_too():
    with pytest.raises(ValidationError):
        CareRule(id="care-fan", channel=Channel.FAN, schedule=(_step("on", 8), _step("on", 9)))


# --- run sheet: retained level -------------------------------------------------------------------


def _with_retained(channel: Channel, level) -> tuple[dict, int]:
    data = make_run_sheet().model_dump(mode="json")
    index = next(i for i, plan in enumerate(data["channels"]) if plan["channel"] == channel.value)
    data["channels"][index]["retained_level"] = level
    return data, index


@pytest.mark.parametrize("channel", list(Channel))
def test_a_retained_level_above_the_channels_range_is_refused_with_the_bound(channel):
    high = LEVEL_RANGES[channel][1]
    data, index = _with_retained(channel, high + 1)

    assert problems(RunSheet, data) == [
        {
            "type": "less_than_equal",
            "loc": ("channels", index, "retained_level"),
            "input": high + 1,
            "ctx": {"le": high},
        }
    ]


@pytest.mark.parametrize("channel", list(Channel))
def test_a_retained_level_below_the_channels_range_is_refused_with_the_bound(channel):
    low = LEVEL_RANGES[channel][0]
    data, index = _with_retained(channel, low - 1)

    assert problems(RunSheet, data) == [
        {
            "type": "greater_than_equal",
            "loc": ("channels", index, "retained_level"),
            "input": low - 1,
            "ctx": {"ge": low},
        }
    ]


@pytest.mark.parametrize("channel", list(Channel))
@pytest.mark.parametrize("end", [0, 1])
def test_a_retained_level_at_either_end_of_the_range_or_none_is_accepted(channel, end):
    level = LEVEL_RANGES[channel][end]
    data, index = _with_retained(channel, level)
    assert RunSheet.model_validate(data).channels[index].retained_level == level

    data, index = _with_retained(channel, None)
    assert RunSheet.model_validate(data).channels[index].retained_level is None


def test_a_channel_plan_built_directly_is_checked_too():
    with pytest.raises(ValidationError):
        ChannelPlan(channel=Channel.FAN, ownership=Ownership.HOST, retained_level=40)


# --- stored records keep loading -----------------------------------------------------------------


def _stored_safety_json() -> str:
    """A configuration as an earlier version stored it: a repeated id and negative times."""
    data = safety_with_rules("overheat", "overheat")
    data["rules"][0]["validity_seconds"] = -5
    data["rules"][1]["duration_seconds"] = -1
    return SafetyConfig.model_validate(data, context=STORED).model_dump_json()


def _stored_sheet_json() -> str:
    data, _ = _with_retained(Channel.FAN, 40)
    data["timed_actions"] = [_timed("on"), _timed("on")]
    data["manual_tasks"] = [_task("photo"), _task("photo")]
    data["end_actions"] = [_end(Channel.LIGHT), _end(Channel.LIGHT)]
    return RunSheet.model_validate(data, context=STORED).model_dump_json()


def test_a_stored_safety_config_that_breaks_the_input_checks_still_loads_unchanged():
    stored = _stored_safety_json()

    loaded = SafetyConfig.model_validate_json(stored, context=STORED)

    assert loaded.model_dump_json() == stored
    with pytest.raises(ValidationError):  # the same body coming in is refused
        SafetyConfig.model_validate_json(stored)


def test_a_stored_run_sheet_that_breaks_the_input_checks_still_loads_unchanged():
    stored = _stored_sheet_json()

    loaded = RunSheet.model_validate_json(stored, context=STORED)

    assert loaded.model_dump_json() == stored
    with pytest.raises(ValidationError):
        RunSheet.model_validate_json(stored)


def test_a_stored_run_sheet_with_repeated_rule_and_step_ids_still_loads_unchanged():
    data = make_run_sheet().model_dump(mode="json")
    data["feedback_rules"] = [_feedback("humid"), _feedback("humid")]
    data["care_rules"] = [_care("care-fan", "on", "on"), _care("care-fan")]
    stored = RunSheet.model_validate(data, context=STORED).model_dump_json()

    loaded = RunSheet.model_validate_json(stored, context=STORED)

    assert loaded.model_dump_json() == stored
    with pytest.raises(ValidationError):  # the same body coming in is refused
        RunSheet.model_validate_json(stored)


def test_the_stored_context_does_not_lift_the_older_checks():
    """Only the checks added for input are lifted: a level outside its range in a timed action
    was refused on reads before, and still is."""
    data = make_run_sheet().model_dump(mode="json")
    data["timed_actions"][0]["level"] = 101

    with pytest.raises(ValidationError):
        RunSheet.model_validate(data, context=STORED)


def test_the_stored_context_cannot_be_changed():
    with pytest.raises(TypeError):
        STORED["stored"] = False  # type: ignore[index]
