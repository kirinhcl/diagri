"""Strip operators' free-text notes from action triggers, keeping only known categories."""

from __future__ import annotations

import re
from typing import NamedTuple

_ID = r"[A-Za-z0-9_.-]+"
_KINDS = "rule|protect|end|experiment_action|care|protection"
_BARE = re.compile(r"(manual|interlock|watchdog)")
_WITH_NOTE = re.compile(rf"(manual|planned irrigation {_ID}): .*", re.DOTALL)
_PLAIN = re.compile(rf"planned irrigation {_ID}|(?:{_KINDS}):{_ID}")


class CleanedTrigger(NamedTuple):
    value: str
    note_dropped: bool
    other: bool


def clean_trigger(trigger: str) -> CleanedTrigger:
    if _BARE.fullmatch(trigger) or _PLAIN.fullmatch(trigger):
        return CleanedTrigger(trigger, False, False)
    noted = _WITH_NOTE.fullmatch(trigger)
    if noted:
        return CleanedTrigger(noted.group(1), True, False)
    return CleanedTrigger("other", False, True)
