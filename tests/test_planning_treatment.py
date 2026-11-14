"""Does a run sheet apply its round's treatment, and did the device record it?"""

from growbridge.archive.models import Channel, ChannelPlan, Ownership, TimedAction
from growbridge.control.device import MODULES
from growbridge.planning.treatment import (
    DEVICE_FIELDS,
    allocated,
    check_treatment,
    delivered,
    unread,
)
from growbridge.sim.fixtures import make_protocol, make_run_sheet

PROTOCOL = make_protocol()  # rounds 1-4: high (light 70), control (40), control, high
HIGH, CONTROL = (next(t for t in PROTOCOL.treatments if t.id == i) for i in ("high", "control"))


def light(*levels: int):
    actions = [
        TimedAction(id=f"light-{n}", channel=Channel.LIGHT, at=f"{6 + n:02d}:00", level=level)
        for n, level in enumerate(levels)
    ]
    return make_run_sheet(timed_actions=tuple(actions))


def codes(sheet, round_number):
    return [f.code for f in check_treatment(sheet, PROTOCOL, round_number) if f.blocking]


def test_a_schedule_at_the_rounds_level_with_nights_off_applies_it():
    assert codes(light(70, 0), 1) == []
    assert codes(light(40, 0), 2) == []


def test_the_other_treatments_level_is_refused_with_the_reason():
    (finding,) = check_treatment(light(40, 0), PROTOCOL, 1)

    assert finding.blocking and finding.code == "treatment_not_applied"
    assert "round 1" in finding.message and "light to 70" in finding.message


def test_a_retained_level_on_a_device_owned_channel_applies_nothing():
    """What qwen3.6 filed: light 'retained' at 70 by the device, no timed action at all."""
    plans = (ChannelPlan(channel=Channel.LIGHT, ownership=Ownership.DEVICE, retained_level=70),)
    sheet = make_run_sheet(channels=plans, timed_actions=())

    (finding,) = check_treatment(sheet, PROTOCOL, 1)

    assert "not host-controlled" in finding.message


def test_extra_levels_on_the_treatment_channel_are_refused():
    (finding,) = check_treatment(light(70, 55, 0), PROTOCOL, 1)

    assert "also set light to [55]" in finding.message


def test_a_round_without_an_allocation_must_apply_some_treatment():
    assert codes(light(40, 0), 9) == [] and codes(light(70, 0), None) == []
    (finding,) = check_treatment(light(60, 0), PROTOCOL, None)

    assert "none of the protocol's treatments" in finding.message


def test_a_protocol_without_level_factors_checks_nothing():
    plain = PROTOCOL.model_copy(
        update={
            "treatments": tuple(t.model_copy(update={"factors": {}}) for t in PROTOCOL.treatments)
        }
    )

    assert check_treatment(light(60), plain, 1) == ()
    assert allocated(PROTOCOL, 1) == HIGH and allocated(PROTOCOL, 5) is None


def reading(level):
    return {"light": {"level": level, "on": 1}, "sensor": {"temp": 22.0}}


def test_recorded_levels_must_show_the_treatment():
    night_and_day = [reading(70)] * 16 + [reading(0)] * 8

    assert delivered(night_and_day, HIGH) == []
    assert delivered([reading(20)] * 10, HIGH) == ["light was never at 70 (recorded [20])"]
    slipped = delivered([reading(70)] * 5 + [reading(50)] * 5, HIGH)
    assert slipped == ["light was at other levels in 50 % of the readings"]


def test_samples_without_a_level_cannot_be_checked_and_say_so():
    rows = [{"temp": 21.0}] * 3

    assert delivered(rows, CONTROL) == [] and unread(rows, CONTROL) == ["light"]
    assert unread([reading(40)], CONTROL) == []


def test_the_device_fields_follow_the_device_driver():
    assert DEVICE_FIELDS == MODULES
