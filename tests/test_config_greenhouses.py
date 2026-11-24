"""The greenhouse registry and the multi-user switch in the settings."""

import pytest
from pydantic import ValidationError

from growbridge.archive.models import Channel, RuleAction
from growbridge.config import Greenhouse, Settings


def settings(**fields) -> Settings:
    return Settings(device="AC5-LOCAL", token="t" * 32, data_dir="/tmp/unused", **fields)


def test_default_registry_is_the_local_device():
    registry = settings().greenhouse_registry()

    assert registry == (Greenhouse(id="gh-01", name="Greenhouse 1", device_id="AC5-LOCAL"),)


def test_configured_registry_is_returned_in_order():
    houses = [
        {"id": "gh-01", "name": "North", "device_id": "AC5-LOCAL"},
        {"id": "gh-02", "name": "South", "device_id": "AC5-2"},
    ]

    registry = settings(greenhouses=houses).greenhouse_registry()

    assert [house.id for house in registry] == ["gh-01", "gh-02"]


@pytest.mark.parametrize(
    "houses",
    [
        [
            {"id": "gh-01", "name": "A", "device_id": "AC5-LOCAL"},
            {"id": "gh-01", "name": "B", "device_id": "AC5-2"},
        ],
        [
            {"id": "gh-01", "name": "A", "device_id": "AC5-LOCAL"},
            {"id": "gh-02", "name": "B", "device_id": "AC5-LOCAL"},
        ],
    ],
)
def test_ids_and_devices_unique(houses):
    with pytest.raises(ValidationError, match="unique"):
        settings(greenhouses=houses)


def test_local_device_must_be_registered():
    with pytest.raises(ValidationError, match="AC5-LOCAL"):
        settings(greenhouses=[{"id": "gh-02", "name": "B", "device_id": "AC5-2"}])


@pytest.mark.parametrize("bad_id", ["", "GH-1", "-gh", "g" * 33, "gh/1"])
def test_greenhouse_id_format(bad_id):
    with pytest.raises(ValidationError):
        Greenhouse(id=bad_id, name="x", device_id="d")


def test_multi_user_defaults_off():
    assert settings().multi_user is False


IDLE = {"light": 0, "exhaust": 10, "fan": 0}


def test_idle_levels_on_a_greenhouse():
    houses = [{"id": "gh-01", "name": "North", "device_id": "AC5-LOCAL", "idle": IDLE}]

    levels = settings(greenhouses=houses).local_idle()

    assert levels == (
        RuleAction(channel=Channel.LIGHT, level=0),
        RuleAction(channel=Channel.EXHAUST, level=10),
        RuleAction(channel=Channel.FAN, level=0),
    )


def test_idle_levels_are_listed_in_channel_order():
    houses = [
        {"id": "gh-01", "name": "North", "device_id": "AC5-LOCAL", "idle": {"fan": 2, "light": 5}}
    ]

    levels = settings(greenhouses=houses).local_idle()

    assert [action.channel for action in levels] == [Channel.LIGHT, Channel.FAN]


def test_another_greenhouse_s_idle_is_not_the_local_one():
    houses = [
        {"id": "gh-01", "name": "North", "device_id": "AC5-LOCAL"},
        {"id": "gh-02", "name": "South", "device_id": "AC5-2", "idle": IDLE},
    ]

    assert settings(greenhouses=houses).local_idle() == ()


@pytest.mark.parametrize("idle", [{"pump": 0}, {"fan": 11}, {"light": -1}, {"heater": 1}])
def test_idle_refuses_the_pump_unknown_channels_and_out_of_range_levels(idle):
    with pytest.raises(ValidationError):
        Greenhouse(id="gh-01", name="One", device_id="AC5", idle=idle)


def test_top_level_idle_is_for_the_implicit_greenhouse():
    implicit = settings(idle={"light": 0})

    assert implicit.local_idle() == (RuleAction(channel=Channel.LIGHT, level=0),)
    assert implicit.greenhouse_registry()[0].idle == {Channel.LIGHT: 0}


def test_top_level_idle_with_registered_greenhouses_is_refused():
    houses = [{"id": "gh-01", "name": "North", "device_id": "AC5-LOCAL"}]

    with pytest.raises(ValidationError, match="idle"):
        settings(idle={"light": 0}, greenhouses=houses)


def test_top_level_pump_idle_is_refused():
    with pytest.raises(ValidationError):
        settings(idle={"pump": 0})


def test_no_idle_by_default():
    assert settings().local_idle() == ()
