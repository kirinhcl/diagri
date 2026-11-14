import json

import pytest
from pydantic import ValidationError

from growbridge.archive.models import DEFAULT_FROZEN_MINUTES, FrozenCheck, SafetyConfig
from growbridge.sim.fixtures import make_safety

DEFAULTS = {"temp": 120.0, "humi": 60.0, "co2": 60.0, "tempSoil": 240.0}


def test_old_safety_config_without_frozen_loads_with_defaults():
    stored = make_safety().model_dump(mode="json")
    stored.pop("frozen", None)
    config = SafetyConfig.model_validate_json(json.dumps(stored))
    assert config.frozen.minutes == DEFAULTS
    assert config.frozen.max_gap_seconds == 600.0


@pytest.mark.parametrize("bad", [0, -5, float("nan"), float("inf")])
def test_frozen_rejects_non_positive_or_non_finite_minutes(bad):
    with pytest.raises(ValidationError):
        FrozenCheck(minutes={"temp": bad})


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf")])
def test_frozen_rejects_a_non_positive_gap(bad):
    with pytest.raises(ValidationError):
        FrozenCheck(max_gap_seconds=bad)


def test_empty_minutes_means_check_nothing():
    assert FrozenCheck(minutes={}).minutes == {}


def test_frozen_round_trips():
    config = make_safety(frozen=FrozenCheck(minutes={"temp": 30.0}, max_gap_seconds=90.0))
    again = SafetyConfig.model_validate_json(config.model_dump_json())
    assert again == config
    assert again.frozen.minutes == {"temp": 30.0}
    assert again.digest() == config.digest()


def test_default_minutes_are_not_shared_between_configs():
    first = FrozenCheck()
    first.minutes["temp"] = 1.0
    assert FrozenCheck().minutes == DEFAULTS
    assert DEFAULT_FROZEN_MINUTES == DEFAULTS
