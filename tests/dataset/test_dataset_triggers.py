import pytest

from growbridge.archive.models import CareRule, Channel, TimedAction
from growbridge.dataset.triggers import CleanedTrigger, clean_trigger
from growbridge.executor.engine import care_steps
from growbridge.sim.fixtures import make_run_sheet

CASES = [
    ("manual", "manual", False, False),
    ("manual: watered by hand", "manual", True, False),
    ("planned irrigation p-1.2", "planned irrigation p-1.2", False, False),
    ("planned irrigation p1: note, with text", "planned irrigation p1", True, False),
    ("rule:r1", "rule:r1", False, False),
    ("protect:a_b", "protect:a_b", False, False),
    ("end:x", "end:x", False, False),
    ("experiment_action:x.y", "experiment_action:x.y", False, False),
    ("care:c", "care:c", False, False),
    ("care:care-evening/on", "care:care-evening/on", False, False),
    ("protection:p", "protection:p", False, False),
    ("interlock", "interlock", False, False),
    ("watchdog", "watchdog", False, False),
    ("rule: free text", "other", False, True),
    ("manualish", "other", False, True),
    ("planned irrigation", "other", False, True),
    ("rule:", "other", False, True),
    ("", "other", False, True),
    ("care:a/b/c", "other", False, True),
    ("care:/on", "other", False, True),
    ("rule:a/b", "other", False, True),
]


@pytest.mark.parametrize(("trigger", "value", "dropped", "other"), CASES)
def test_clean_trigger(trigger, value, dropped, other):
    assert clean_trigger(trigger) == CleanedTrigger(value, dropped, other)


def test_a_care_cause_built_like_the_executor_keeps_its_category():
    # Two care rules that share a step id, as #24 allows; the executor names each step
    # `<care id>/<step id>` and writes the cause `care:<that id>`.
    on = TimedAction(id="on", channel=Channel.LIGHT, at="06:00", level=60)
    sheet = make_run_sheet(
        timed_actions=(),
        care_rules=(
            CareRule(id="care-morning", channel=Channel.LIGHT, schedule=(on,)),
            CareRule(id="care-evening", channel=Channel.LIGHT, schedule=(on,)),
        ),
    )
    causes = [f"care:{step.id}" for step in care_steps(sheet)]
    assert causes == ["care:care-morning/on", "care:care-evening/on"]
    for cause in causes:
        assert clean_trigger(cause) == CleanedTrigger(cause, False, False)
