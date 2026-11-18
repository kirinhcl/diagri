import pytest

from growbridge.dataset.triggers import CleanedTrigger, clean_trigger

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
    ("protection:p", "protection:p", False, False),
    ("interlock", "interlock", False, False),
    ("watchdog", "watchdog", False, False),
    ("rule: free text", "other", False, True),
    ("manualish", "other", False, True),
    ("planned irrigation", "other", False, True),
    ("rule:", "other", False, True),
    ("", "other", False, True),
]


@pytest.mark.parametrize(("trigger", "value", "dropped", "other"), CASES)
def test_clean_trigger(trigger, value, dropped, other):
    assert clean_trigger(trigger) == CleanedTrigger(value, dropped, other)
