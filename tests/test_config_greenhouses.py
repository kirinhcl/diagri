"""The greenhouse registry and the multi-user switch in the settings."""

import pytest
from pydantic import ValidationError

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
