"""What a model role is told about its project when a task starts (architecture doc §5.2,
"对话上下文"): the open rounds with their protocol and stages, and the controlled device.

Run sheets must name the round's own project, protocol version and device; a model that is not
told those ids invents them, and the draft is refused only at submission. A round that takes
drafts also gets ids for its next run sheet, so a model never has to choose between inventing an
id and refusing to.
"""

from __future__ import annotations

from typing import Any

from growbridge.archive.models import ResearchTask
from growbridge.workflow.listing import project_detail
from growbridge.workflow.states import RoundState

MAX_ROUNDS = 3
CLOSED_ROUNDS = frozenset({RoundState.DELIVERED.value, RoundState.ABORTED.value})
DRAFTING = frozenset({RoundState.DESIGNING.value, RoundState.STAGE_REVIEW.value})
ROUND_REF = "round:"


def _new_stage(row: dict[str, Any], stages: Any, protocol: Any) -> dict[str, Any]:
    """Ids for the next run sheet of a round that takes drafts. They are new by construction (the
    round id is unique); the experiment stays the round's own once a stage has named one."""
    number = len(stages) + 1
    names = tuple(protocol.stages) if protocol is not None else ()
    experiment = stages[0].experiment_id if stages else f"exp-{row['round_id']}"
    return {
        "stage_name": names[number - 1] if number <= len(names) else None,
        "run_sheet_id": f"sheet-{row['round_id']}-{number}",
        "run_sheet_version": 1,
        "stage_id": f"stage-{row['round_id']}-{number}",
        "experiment_id": experiment,
    }


def _round(workflow: Any, row: dict[str, Any]) -> dict[str, Any]:
    stages = workflow.store.stages_of_round(row["round_id"])
    protocol = workflow.store.protocol(row["protocol_id"], row["protocol_version"])
    out = {
        "round_id": row["round_id"],
        "state": row["state"],
        "protocol_id": row["protocol_id"],
        "protocol_version": row["protocol_version"],
        "awaiting_choice": row["awaiting_choice"],
        "stages": [
            {
                "stage_id": stage.stage_id,
                "state": stage.state.value,
                "experiment_id": stage.experiment_id,
                "run_sheet_id": stage.run_sheet_id,
                "run_sheet_version": stage.run_sheet_version,
            }
            for stage in stages
        ],
    }
    if row["state"] in DRAFTING:
        out["new_stage"] = _new_stage(row, stages, protocol)
    return out


def project_context(workflow: Any, control: Any, timezone: str, task: ResearchTask) -> dict:
    """The context of ``task``: its round first (when it names one), then the newest open ones,
    the protocol version of each listed round, the device id and the site's timezone."""
    detail = project_detail(workflow.store, task.project_id) or {"rounds": []}
    named = {ref.removeprefix(ROUND_REF) for ref in task.input_refs if ref.startswith(ROUND_REF)}
    rows = [r for r in detail["rounds"] if r["round_id"] in named]
    rows += [
        r
        for r in detail["rounds"]
        if r["round_id"] not in named and r["state"] not in CLOSED_ROUNDS
    ]
    rounds = [_round(workflow, row) for row in rows[:MAX_ROUNDS]]
    protocols = {}
    for item in rounds:
        key = f"{item['protocol_id']} v{item['protocol_version']}"
        protocol = workflow.store.protocol(item["protocol_id"], item["protocol_version"])
        if protocol is not None and key not in protocols:
            protocols[key] = protocol.model_dump(mode="json")
    return {
        "device_id": getattr(control, "device_id", None),
        "timezone": timezone,
        "rounds": rounds,
        "protocols": protocols,
    }
