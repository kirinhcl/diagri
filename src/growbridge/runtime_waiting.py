"""What the alert for a waiting stage says and carries (split out of ``runtime``)."""

import json
from collections.abc import Mapping
from typing import Any


def waiting_message(item: Mapping[str, Any]) -> str:
    """Why a stage waits: its state, the event that put it there and what the event carried."""
    detail = {
        name: value
        for name, value in item["detail"].items()
        if name != "right_number" and value != item["event"]
    }
    text = f"Stage {item['stage_id']} is {item['state']} after {item['event']}"
    return f"{text}: {json.dumps(detail, sort_keys=True)}" if detail else text


def waiting_params(item: Mapping[str, Any]) -> dict[str, object]:
    """The params of the ``stage_waiting`` alert: the history entry as stored."""
    return {
        "stage_id": item["stage_id"],
        "entry_id": item["entry"],
        "state": item["state"],
        "event": item["event"],
        "detail": item["detail"],
    }
