"""Each run sheet finding names a message code and carries the params the console builds its
text from (growbridge.codes, CODES["finding"]); the English message is kept for API clients."""

import re

import pytest

from growbridge.archive.models import (
    LEVEL_RANGES,
    CareRule,
    Channel,
    ChannelPlan,
    Condition,
    EvidenceCard,
    ManualTask,
    Ownership,
    ProtectionRule,
    RuleAction,
    SamplingPlan,
    TimedAction,
)
from growbridge.codes import CODES
from growbridge.planning.design import check_experimental_design
from growbridge.planning.findings import message_code
from growbridge.planning.treatment import check_treatment
from growbridge.planning.validate import check_evidence, validate_run_sheet
from growbridge.ports import Capabilities, Finding
from growbridge.sim.fixtures import humidity_rule, make_protocol, make_run_sheet, make_safety
from tests.planning.test_planning_design import alloc, protocol_with

CAPS = Capabilities(
    version="test",
    sensors={"humi": "%", "temp": "C"},
    level_ranges=dict(LEVEL_RANGES),
    outlets={},
)
CHINESE = re.compile(r"[㐀-鿿]")


def one(findings: tuple[Finding, ...], code: str, variant: str = "") -> Finding:
    (found,) = [f for f in findings if f.code == code and f.variant == variant]
    assert message_code(found.code, found.variant) in CODES["finding"]
    return found


def validated(sheet, safety=None) -> tuple[Finding, ...]:
    return validate_run_sheet(sheet, CAPS, safety)


def with_plan(channel: Channel, **plan):
    base = make_run_sheet()
    others = tuple(p for p in base.channels if p.channel is not channel)
    return base.model_copy(update={"channels": (*others, ChannelPlan(channel=channel, **plan))})


PUMP_ON = RuleAction(channel=Channel.PUMP, level=1)


def test_a_write_to_a_device_owned_channel_names_its_source_and_channel() -> None:
    sheet = with_plan(Channel.LIGHT, ownership=Ownership.DEVICE)
    findings = [f for f in validated(sheet) if f.code == "device_owned_write"]
    assert findings[0].params == {
        "source_kind": "timed_action",
        "source": "light-on",
        "channel": "light",
    }


def test_each_kind_of_action_names_its_source_kind() -> None:
    care = CareRule(
        id="care",
        channel=Channel.PUMP,
        schedule=(TimedAction(id="c1", channel=Channel.PUMP, at="01:00", level=1),),
    )
    protection = ProtectionRule(
        id="p1",
        sensor="temp",
        unit="C",
        validity_seconds=20,
        trigger=Condition(op=">", value=35),
        duration_seconds=30,
        action=PUMP_ON,
    )
    sheet = make_run_sheet(
        feedback_rules=(humidity_rule(id="r1", release=PUMP_ON),),
        care_rules=(care,),
        end_actions=(PUMP_ON,),
    )
    findings = validated(sheet, make_safety(rules=(protection,)))
    seen = {
        (f.params["source_kind"], f.params["source"]) for f in findings if f.code == "pump_action"
    }
    assert seen == {
        ("feedback_release", "r1"),
        ("care_step", "care/c1"),
        ("end_action", "1"),
        ("protection_rule", "p1"),
    }


def test_a_pump_start_says_which_step_and_drops_the_seconds_term() -> None:
    pump_on = TimedAction(id="pump-on", channel=Channel.PUMP, at="08:00", level=1)
    sheet = make_run_sheet(timed_actions=(*make_run_sheet().timed_actions, pump_on))
    found = one(validated(sheet), "pump_action")
    assert found.params == {"source_kind": "timed_action", "source": "pump-on"}
    assert "with seconds" not in found.message
    assert found.message.startswith("timed action pump-on would start the pump")


def test_a_level_outside_the_range_carries_the_range() -> None:
    bad = TimedAction(id="hot", channel=Channel.LIGHT, at="08:00", level=99)
    sheet = make_run_sheet(timed_actions=(*make_run_sheet().timed_actions, bad))
    caps = CAPS.model_copy(update={"level_ranges": {Channel.LIGHT: (0, 80)}})
    found = one(validate_run_sheet(sheet, caps), "level_range")
    assert found.params == {
        "source_kind": "timed_action",
        "source": "hot",
        "channel": "light",
        "level": 99,
        "min": 0,
        "max": 80,
    }


def test_a_pump_left_to_the_device_has_no_params() -> None:
    found = one(validated(with_plan(Channel.PUMP, ownership=Ownership.DEVICE)), "pump_device_owned")
    assert found.params == {}


def test_an_unknown_sensor_names_the_rule_and_sensor() -> None:
    sheet = make_run_sheet(feedback_rules=(humidity_rule(id="r1", sensor="soil"),))
    found = one(validated(sheet), "unknown_sensor")
    assert found.params == {"rule": "r1", "sensor": "soil"}


def test_a_unit_mismatch_names_both_units() -> None:
    sheet = make_run_sheet(feedback_rules=(humidity_rule(id="r1", unit="ppm"),))
    found = one(validated(sheet), "unit_mismatch")
    assert found.params == {
        "rule": "r1",
        "sensor": "humi",
        "device_unit": "%",
        "rule_unit": "ppm",
    }


def test_humidity_feedback_on_another_channel_names_the_rule() -> None:
    action = RuleAction(channel=Channel.LIGHT, level=10)
    sheet = make_run_sheet(feedback_rules=(humidity_rule(id="r1", action=action),))
    assert one(validated(sheet), "humidity_exhaust_only").params == {"rule": "r1"}


def test_conflicting_rules_name_both_rules_the_channel_and_priority() -> None:
    a = humidity_rule(id="a")
    b = humidity_rule(id="b", action=RuleAction(channel=Channel.EXHAUST, level=60))
    found = one(validated(make_run_sheet(feedback_rules=(a, b))), "rule_conflict")
    assert found.params == {
        "rule_a": "a",
        "rule_b": "b",
        "channel": "exhaust",
        "priority": a.priority,
    }


def test_a_safety_conflict_names_the_rule_the_protection_and_both_levels() -> None:
    rule = humidity_rule(
        id="warm",
        sensor="temp",
        unit="C",
        trigger=Condition(op=">", value=30),
        recover=Condition(op="<", value=25),
        action=RuleAction(channel=Channel.LIGHT, level=80),
        release=None,
    )
    safety = make_safety()
    found = one(validated(make_run_sheet(feedback_rules=(rule,)), safety), "safety_conflict")
    protection = next(p for p in safety.rules if p.sensor == "temp")
    assert found.params == {
        "rule": "warm",
        "protection": protection.id,
        "channel": "light",
        "level": 80,
        "protection_level": protection.action.level,
    }


def test_rule_validity_shorter_than_the_interval() -> None:
    sheet = make_run_sheet(
        sampling=SamplingPlan(interval_seconds=60, max_gap_seconds=300),
        feedback_rules=(humidity_rule(id="r1", validity_seconds=20),),
    )
    found = one(validated(sheet), "sampling", "validity")
    assert found.params == {"rule": "r1", "validity_seconds": 20, "interval_seconds": 60}


def test_a_non_positive_sampling_interval() -> None:
    sheet = make_run_sheet(sampling=SamplingPlan(interval_seconds=0, max_gap_seconds=120))
    assert one(validated(sheet), "sampling", "interval").params == {"interval_seconds": 0}


def test_a_max_gap_shorter_than_the_interval() -> None:
    sheet = make_run_sheet(sampling=SamplingPlan(interval_seconds=60, max_gap_seconds=30))
    assert one(validated(sheet), "sampling", "max_gap").params == {"max_gap_seconds": 30}


def test_a_non_positive_rule_duration() -> None:
    sheet = make_run_sheet(feedback_rules=(humidity_rule(id="r1", duration_seconds=0),))
    found = one(validated(sheet), "duration", "rule")
    assert found.params["rule"] == "r1" and found.params["duration_seconds"] == 0
    assert set(found.params) == {"rule", "duration_seconds", "min_switch_seconds"}


def test_a_non_positive_protection_duration() -> None:
    protection = ProtectionRule(
        id="p1",
        sensor="temp",
        unit="C",
        validity_seconds=20,
        trigger=Condition(op=">", value=35),
        duration_seconds=0,
        action=RuleAction(channel=Channel.LIGHT, level=0),
    )
    found = one(
        validated(make_run_sheet(), make_safety(rules=(protection,))), "duration", "protection"
    )
    assert found.params == {"protection": "p1", "duration_seconds": 0}


def test_a_non_positive_run_duration() -> None:
    found = one(validated(make_run_sheet(duration_seconds=0)), "duration", "run")
    assert found.params == {"duration_seconds": 0}


def test_a_non_positive_wait() -> None:
    found = one(validated(make_run_sheet(max_wait_seconds=0)), "wait")
    assert found.params == {"max_wait_seconds": 0}


def test_a_missing_tolerance_names_the_channel() -> None:
    findings = validated(make_run_sheet())
    channels = {f.params["channel"] for f in findings if f.code == "missing_tolerance"}
    assert channels and channels <= {c.value for c in Channel}


def test_a_manual_task_names_its_kind_id_and_time() -> None:
    sheet = make_run_sheet(manual_tasks=(ManualTask(id="shoot", kind="photo", at="09:30"),))
    found = one(validated(sheet), "manual_task")
    assert found.params == {"task_kind": "photo", "task_id": "shoot", "at_local": "09:30"}
    assert not found.blocking


def test_a_manual_irrigation_carries_the_seconds() -> None:
    task = ManualTask(id="water", kind="irrigation", at="09:00", seconds=30)
    found = one(validated(make_run_sheet(manual_tasks=(task,))), "manual_task", "irrigation")
    assert found.params == {"task_id": "water", "at_local": "09:00", "seconds": 30}
    assert "30 s pump run" in found.message


def test_an_action_without_evidence_names_its_source() -> None:
    findings = check_evidence(make_run_sheet(), {})
    found = [f for f in findings if f.code == "no_evidence"]
    assert found[0].params == {"source_kind": "timed_action", "source": found[0].params["source"]}
    assert {f.params["source"] for f in found} == {a.id for a in make_run_sheet().timed_actions}


def evidence_sheet():
    base = make_run_sheet()
    actions = tuple(a.model_copy(update={"evidence": "card-1"}) for a in base.timed_actions)
    return base.model_copy(update={"timed_actions": actions})


def card(**fields) -> EvidenceCard:
    base = {"id": "card-1", "source_class": "paper", "citation": "Doe 2020", "claim": "c"}
    return EvidenceCard(**{**base, "verified": True, **fields})


def test_an_unverified_card_names_the_source_and_the_card() -> None:
    findings = check_evidence(evidence_sheet(), {"card-1": card(verified=False)})
    found = findings[0]
    assert (found.code, found.params["source_kind"], found.params["card_id"]) == (
        "unverified_source",
        "timed_action",
        "card-1",
    )
    assert set(found.params) == {"source_kind", "source", "card_id"}


def test_an_uncalibrated_card_has_no_chinese_in_its_message() -> None:
    findings = check_evidence(evidence_sheet(), {"card-1": card(calibrated=False)})
    found = findings[0]
    assert found.code == "uncalibrated"
    assert set(found.params) == {"source_kind", "source", "card_id"}
    assert found.message.endswith("card card-1 is uncalibrated")


def test_care_and_feedback_evidence_sources() -> None:
    step = TimedAction(id="care-1", channel=Channel.FAN, at="01:00", level=2)
    sheet = make_run_sheet(
        timed_actions=(),
        feedback_rules=(humidity_rule(id="r1"),),
        care_rules=(CareRule(id="care", channel=Channel.FAN, schedule=(step,)),),
    )
    seen = {(f.params["source_kind"], f.params["source"]) for f in check_evidence(sheet, {})}
    assert seen == {("feedback_rule", "r1"), ("care_step", "care/care-1")}


# --- design ---------------------------------------------------------------------------------------


def test_an_unknown_treatment_lists_the_names() -> None:
    allocations = [*make_protocol().allocations, alloc(5, 3, "ghost")]
    found = one(check_experimental_design(protocol_with(allocations)), "unknown_treatment")
    assert found.params == {"treatments": ["ghost"]}


def test_an_undefined_control_names_it() -> None:
    found = one(
        check_experimental_design(make_protocol(control_treatment_id="placebo")),
        "missing_control",
        "undefined",
    )
    assert found.params == {"control": "placebo"}


def declared(found: Finding) -> set[str]:
    return set(CODES["finding"][message_code(found.code, found.variant)].params)


def test_an_unallocated_control_is_named_by_its_name_with_its_id_for_the_details() -> None:
    from growbridge.archive.models import Treatment

    treatments = (*make_protocol().treatments, Treatment(id="extra", name="x"))
    protocol = make_protocol(treatments=treatments, control_treatment_id="extra")
    found = one(check_experimental_design(protocol), "missing_control", "unallocated")
    assert found.params == {"control": "x", "control_id": "extra"}
    assert set(found.params) == declared(found)


def test_thin_treatments_are_listed_by_name_with_their_ids_for_the_details() -> None:
    allocations = [alloc(1, 1, "control"), alloc(2, 1, "high")]
    found = one(check_experimental_design(protocol_with(allocations)), "no_replication")
    assert found.params == {
        "treatments": ["light 40 %", "light 70 %"],
        "treatment_ids": ["control", "high"],
    }
    assert set(found.params) == declared(found)
    assert "['control', 'high']" in found.message  # the English message keeps the ids


def test_a_treatment_without_a_name_is_named_by_its_id() -> None:
    from growbridge.archive.models import Treatment

    high = make_protocol().treatments[1]
    unnamed = (Treatment(id="control", name="", factors={"light": 40}), high)
    allocations = [alloc(1, 1, "control"), alloc(2, 1, "high")]
    found = one(
        check_experimental_design(protocol_with(allocations, treatments=unnamed)), "no_replication"
    )
    assert found.params["treatments"] == ["control", "light 70 %"]


def test_an_unbalanced_block_names_the_block_as_text() -> None:
    allocations = [
        alloc(1, 1, "control"),
        alloc(2, 1, "control"),
        alloc(3, 2, "high"),
        alloc(4, 2, "control"),
        alloc(5, 3, "high"),
        alloc(6, 3, "control"),
        alloc(7, 4, "control"),
        alloc(8, 4, "high"),
    ]
    findings = check_experimental_design(protocol_with(allocations))
    found = next(f for f in findings if f.code == "unbalanced_block")
    assert found.params == {"block": "1"}


def test_confounding_with_time_has_no_params() -> None:
    allocations = [
        alloc(1, 1, "control"),
        alloc(2, 1, "control"),
        alloc(3, 2, "high"),
        alloc(4, 2, "high"),
    ]
    found = one(check_experimental_design(protocol_with(allocations)), "confounded_with_time")
    assert found.params == {}


def test_a_seed_that_gives_other_allocations_is_a_hint() -> None:
    from growbridge.planning.design import randomize_series

    allocations = randomize_series(("control", "high"), blocks=12, seed=11)
    findings = check_experimental_design(protocol_with(allocations, randomization_seed=12))
    found = one(findings, "seed_mismatch", "differs")
    assert found.params == {} and not found.blocking


def test_a_seed_that_cannot_be_regenerated(monkeypatch: pytest.MonkeyPatch) -> None:
    from growbridge.planning import design

    def refuse(*_args):
        raise ValueError("no")

    monkeypatch.setattr(design, "randomize_series", refuse)
    found = one(check_experimental_design(make_protocol()), "seed_mismatch", "unreproducible")
    assert found.params == {} and not found.blocking


# --- treatment ------------------------------------------------------------------------------------

PROTOCOL = make_protocol()  # round 1 is allocated "high" (light 70)


def light(*levels: int):
    actions = [
        TimedAction(id=f"light-{n}", channel=Channel.LIGHT, at=f"{6 + n:02d}:00", level=level)
        for n, level in enumerate(levels)
    ]
    return make_run_sheet(timed_actions=tuple(actions))


def test_a_missing_level_gives_a_no_action_problem() -> None:
    (finding,) = check_treatment(light(40, 0), PROTOCOL, 1)
    assert (finding.code, finding.variant) == ("treatment_not_applied", "")
    assert finding.params == {
        "round": 1,
        "treatment": "light 70 %",
        "treatment_id": "high",
        "problems": [{"kind": "no_action", "channel": "light", "level": 70, "other": None}],
    }
    assert set(finding.params) == declared(finding)
    assert "no timed action sets light to 70" in finding.message
    assert "treatment high (light 70)" in finding.message  # the English message keeps the id


def test_other_levels_give_one_problem_each() -> None:
    (finding,) = check_treatment(light(70, 40, 30, 0), PROTOCOL, 1)
    assert finding.params["problems"] == [
        {"kind": "other_levels", "channel": "light", "level": 70, "other": 30},
        {"kind": "other_levels", "channel": "light", "level": 70, "other": 40},
    ]


def test_a_device_owned_channel_gives_a_not_host_problem() -> None:
    plans = (ChannelPlan(channel=Channel.LIGHT, ownership=Ownership.DEVICE, retained_level=70),)
    sheet = make_run_sheet(channels=plans, timed_actions=())
    (finding,) = check_treatment(sheet, PROTOCOL, 1)
    assert finding.params["problems"] == [
        {"kind": "not_host", "channel": "light", "level": None, "other": None}
    ]
    assert "light is not host-controlled" in finding.message


def test_a_round_without_a_single_allocation_lists_the_treatments_it_could_not_apply() -> None:
    (finding,) = check_treatment(light(55, 0), PROTOCOL, None)
    assert (finding.code, finding.variant) == ("treatment_not_applied", "none")
    assert finding.params == {
        "round": None,
        "treatments": ["light 40 %", "light 70 %"],
        "treatment_ids": ["control", "high"],
    }
    assert set(finding.params) == declared(finding)


def test_no_message_carries_chinese() -> None:
    sheet = with_plan(Channel.PUMP, ownership=Ownership.DEVICE).model_copy(
        update={"feedback_rules": (humidity_rule(id="r1", unit="ppm"),)}
    )
    findings = (
        *validated(sheet),
        *check_evidence(sheet, {}),
        *check_evidence(evidence_sheet(), {"card-1": card(calibrated=False)}),
        *check_treatment(light(40, 0), PROTOCOL, 1),
        *check_experimental_design(make_protocol(control_treatment_id="placebo")),
    )
    assert findings
    assert [f.message for f in findings if CHINESE.search(f.message)] == []


def test_finding_messages_keep_their_english_without_chinese() -> None:
    findings = check_evidence(evidence_sheet(), {"card-1": card(calibrated=False)})
    assert "uncalibrated" in findings[0].message and not CHINESE.search(findings[0].message)
