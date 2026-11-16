"""What the console calls a round and a stage instead of their ids. Read only.

A round is named by its project's name and its ``round_number``: its place, from 1, among the
project's rounds of the same protocol (``WorkflowStore.round_number``). A stage is named by those,
its ``stage_index`` (its place, from 1, among its round's stages in creation order) and the growth
``phase`` the round's protocol version gives that place. A lookup that finds nothing answers None
(a project or round that is gone, a protocol that is gone or lists fewer phases than the round has
stages), never an error: a read must not fail for want of a name.
"""

from typing import Any

from growbridge.ports import Denied
from growbridge.workflow.store import RoundRow, StageRow, WorkflowStore

STAGE_NAME_KEYS = ("project_name", "round_number", "stage_index", "phase")


def project_name(store: WorkflowStore, project_id: str) -> str | None:
    """The project's name, read as ``listing.project_detail`` reads it; None once it is gone."""
    row = store.db.one("SELECT name FROM wf_projects WHERE id = ?", (project_id,))
    return None if row is None else row["name"]


def round_names(store: WorkflowStore, round_id: str) -> dict[str, Any]:
    """``project_name`` and ``round_number`` of a round that exists."""
    rnd = store.round(round_id)
    return {
        "project_name": project_name(store, rnd.project_id),
        "round_number": store.round_number(round_id),
    }


def round_phases(store: WorkflowStore, rnd: RoundRow) -> tuple[str, ...]:
    """The growth phases of the round's protocol version, in order; empty once it is gone."""
    protocol = store.protocol(rnd.protocol_id, rnd.protocol_version)
    return () if protocol is None else tuple(protocol.stages)


def stage_place(phases: tuple[str, ...], index: int | None) -> dict[str, Any]:
    """``stage_index`` (from 1) and the ``phase`` at that place; None beyond the phases."""
    if index is None or not 0 < index <= len(phases):
        return {"stage_index": index, "phase": None}
    return {"stage_index": index, "phase": phases[index - 1]}


def stage_names(store: WorkflowStore, stage: StageRow) -> dict[str, Any]:
    """The names of a stage under ``STAGE_NAME_KEYS``."""
    try:
        rnd = store.round(stage.round_id)
    except Denied:  # the round is gone: there is nothing to number the round or the stage by
        found = project_name(store, stage.project_id)
        return {**dict.fromkeys(STAGE_NAME_KEYS), "project_name": found}
    order = [row.stage_id for row in store.stages_of_round(rnd.id)]
    index = order.index(stage.stage_id) + 1 if stage.stage_id in order else None
    return {**round_names(store, rnd.id), **stage_place(round_phases(store, rnd), index)}
