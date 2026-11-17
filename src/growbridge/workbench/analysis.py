"""Workbench routes of the confirmatory analysis (architecture §6.5, §9.1, §9.3), under ``/wb``.

An operator freezes the analysis script of a protocol's latest version before any stage under it
has started, and, once a data snapshot is frozen, starts the one run of that snapshot. Operators
only (a model role is refused with ``model_role``); the two writes also need a recent
re-authentication. Whoever freezes or starts is the session's operator, never a body field.

A run is refused before the sandbox starts, in this order: the protocol belongs to the project and
has a frozen script; the snapshot belongs to a round that runs this protocol version and was not
invalidated; the snapshot is complete and every file matches its digest; no outcome of a held-out
batch is in it; the snapshot was not analysed before.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from growbridge.archive.models import ResearchProtocol, Snapshot
from growbridge.archive.store import Archive
from growbridge.ports import Actor, Denied
from growbridge.research.analysis import MAX_SCRIPT_CHARS, ConfirmatoryRunner
from growbridge.research.holdout import HoldoutRegistry, refuse_holdout_rows
from growbridge.research.preregistration import (
    RULE,
    require_measurements_after,
    require_stages_after,
)
from growbridge.workbench.common import Body
from growbridge.workbench.rounds import Ident, PathId
from growbridge.workbench.scope import project_read, project_write
from growbridge.workflow.access import Access
from growbridge.workflow.service import WorkflowService

OUTPUT_LIMIT = 4000
STARTED = (
    "a confirmatory analysis must be frozen before outcome data is seen: a stage of this"
    " protocol version has already started"
)
FROZEN_NOTE = (
    "The script is frozen and cannot be corrected afterwards; to change the analysis, save the "
    "protocol as a new protocol version and freeze a script for that."
)
Dependency = Callable[..., Awaitable[Actor]]


class FreezeIn(Body):
    project_id: Ident
    script: str = Field(min_length=1, max_length=MAX_SCRIPT_CHARS)


class RunIn(Body):
    project_id: Ident
    protocol_id: Ident
    snapshot_id: Ident


def clipped(text: str) -> str:
    return text if len(text) <= OUTPUT_LIMIT else text[:OUTPUT_LIMIT] + "...[truncated]"


class AnalysisRoutes:
    """The three routes over one workflow, archive and runner."""

    def __init__(
        self,
        workflow: WorkflowService,
        archive: Archive,
        runner: ConfirmatoryRunner,
        holdout: HoldoutRegistry | None,
    ):
        self.workflow = workflow
        self.archive = archive
        self.runner = runner
        self.holdout = holdout

    def protocol(self, protocol_id: str, project_id: str) -> ResearchProtocol:
        found = self.workflow.store.latest_protocol(protocol_id, project_id)
        if found is None:
            raise Denied(
                "state",
                f"no protocol {protocol_id} in project {project_id}",
                reason="protocol_not_found",
                params={"protocol_id": protocol_id, "project_id": project_id},
            )
        return found

    def freeze(self, protocol_id: str, body: FreezeIn, actor: Actor) -> dict:
        protocol = self.protocol(protocol_id, body.project_id)
        if self.workflow.store.protocol_started(protocol.id, protocol.version):
            raise Denied(
                "state",
                STARTED,
                reason="analysis_freeze_too_late",
                params={"protocol_id": protocol.id, "version": protocol.version},
            )
        self.require_no_data_yet(protocol)
        self.runner.freeze_analysis(protocol, body.script.encode("utf-8"), actor.id)
        info = self.runner.frozen_info(protocol)
        assert info is not None  # freeze_analysis registered it
        return {
            "protocol_id": protocol.id,
            "version": protocol.version,
            "script_sha256": info.sha256,
            "frozen_at": info.frozen_at,
            "note": FROZEN_NOTE,
        }

    def state(self, protocol_id: str, project_id: str) -> dict:
        protocol = self.protocol(protocol_id, project_id)
        info = self.runner.frozen_info(protocol)
        stored = self.runner.frozen_script(protocol)
        frozen = None
        if info is not None:
            frozen = {
                "script_sha256": info.sha256,
                "frozen_at": info.frozen_at,
                "frozen_by": info.frozen_by,
                "script": None if stored is None else stored[1].decode("utf-8"),
            }
        experiments = self.workflow.store.experiments_under(protocol.id, protocol.version)
        return {
            "protocol_id": protocol.id,
            "version": protocol.version,
            "started": self.workflow.store.protocol_started(protocol.id, protocol.version),
            "frozen": frozen,
            "snapshots": [
                {
                    "snapshot_id": snap.id,
                    "experiment_id": snap.experiment_id,
                    "complete": snap.complete,
                    "run_status": self.runner.status(snap.id, protocol),
                    "created_at": snap.created_at,
                }
                for experiment in experiments
                for snap in self.archive.snapshots(experiment)
            ],
        }

    def require_no_data_yet(self, protocol: ResearchProtocol) -> None:
        """Early guard: nobody may have seen outcome data before the freeze. A snapshot or a
        manual measurement of an experiment the protocol's rounds use is already data."""
        for experiment in self.workflow.store.experiments_under(protocol.id, protocol.version):
            held = self.archive.snapshots(experiment)
            held = held or self.archive.measurements(experiment, include_corrected=True)
            if held:
                raise Denied(
                    "state",
                    f"experiment {experiment} already has a snapshot or a measurement: {RULE}",
                    reason="analysis_freeze_too_late",
                    params={"protocol_id": protocol.id, "version": protocol.version},
                )

    def snapshot_of(
        self, line: ResearchProtocol, snapshot_id: str
    ) -> tuple[Snapshot, ResearchProtocol]:
        """The snapshot and the protocol version its data was collected under.

        The version comes from the rounds that have a stage for the snapshot's experiment, not
        from the latest saved version. An experiment shared by rounds of more than one version
        (or of another protocol) is ambiguous and refused.
        """
        snap = self.archive.snapshot(snapshot_id)
        versions = (
            () if snap is None else self.workflow.store.protocol_versions_of(snap.experiment_id)
        )
        mine = [version for protocol_id, version in versions if protocol_id == line.id]
        if snap is None or not mine:
            raise Denied(
                "scope",
                f"snapshot {snapshot_id} is not a snapshot of this protocol",
                reason="not_this_protocol",
                params={"protocol_id": line.id},
            )
        if len(versions) > 1:
            raise Denied(
                "scope",
                f"the experiment of snapshot {snapshot_id} belongs to rounds of more than one "
                "protocol version",
                reason="mixed_protocol",
                params={},
            )
        if self.archive.is_invalid(snap.id):
            raise Denied(
                "state",
                f"snapshot {snap.id} was invalidated by a later correction",
                reason="snapshot_invalidated",
                params={"snapshot_id": snap.id},
            )
        protocol = self.workflow.store.protocol(line.id, mine[0])
        assert protocol is not None  # a round runs it
        return snap, protocol

    async def start(self, body: RunIn, actor: Actor) -> dict:
        line = self.protocol(body.protocol_id, body.project_id)
        snap, protocol = self.snapshot_of(line, body.snapshot_id)
        info = self.runner.frozen_info(protocol)
        if info is None or self.runner.frozen_script(protocol) is None:
            raise Denied(
                "state",
                "no analysis script is frozen for this protocol version",
                reason="analysis_script_not_frozen",
                params={"protocol_id": protocol.id, "version": protocol.version},
            )
        starts = self.workflow.store.stage_starts(snap.experiment_id)
        require_stages_after(info.frozen_at, snap.id, starts)
        directory = self.archive.root / "snapshots" / snap.id

        def admit() -> None:  # runs in a worker thread, before anything is claimed
            rows = directory / "measurements.jsonl"
            refuse_holdout_rows(self.holdout, body.project_id, snap.id, rows)
            recorded = self.archive.measurement_recorded_at
            require_measurements_after(info.frozen_at, snap.id, rows, recorded)

        run = await self.runner.run_frozen(protocol, snap, directory, actor.id, admit)
        return {
            "run_id": run.id,
            "status": run.status,
            "exit_code": run.exit_code,
            "timed_out": run.timed_out,
            "stdout": clipped(run.stdout),
            "stderr": clipped(run.stderr),
        }


def add_analysis_routes(
    router: APIRouter,
    operator: Dependency,
    fresh: Dependency,
    workflow: WorkflowService,
    archive: Archive,
    runner: ConfirmatoryRunner,
    holdout: HoldoutRegistry | None = None,
    *,
    access: Access | None = None,
) -> None:
    """Mount the routes on ``router``; ``operator`` and ``fresh`` are the workbench's operator
    dependencies (``fresh`` also asks for a recent re-authentication)."""

    def owned(actor: Actor, protocol_id: str, project_id: str, write: bool = True) -> None:
        unknown = Denied(  # as ``protocol`` answers a protocol that is not in the project
            "state",
            f"no protocol {protocol_id} in project {project_id}",
            reason="protocol_not_found",
            params={"protocol_id": protocol_id, "project_id": project_id},
        )
        check = project_write if write else project_read
        check(access, actor, project_id, lambda: unknown)

    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806
    Fresh = Annotated[Actor, Depends(fresh)]  # noqa: N806
    routes = AnalysisRoutes(workflow, archive, runner, holdout)

    @router.post("/protocols/{protocol_id}/analysis")
    async def freeze_script(protocol_id: PathId, body: FreezeIn, actor: Fresh):
        owned(actor, protocol_id, body.project_id)
        return routes.freeze(protocol_id, body, actor)

    @router.get("/protocols/{protocol_id}/analysis")
    async def analysis_state(
        protocol_id: PathId,
        project_id: Annotated[str, Query(min_length=1, max_length=100)],
        actor: Operator,
    ):
        owned(actor, protocol_id, project_id, write=False)
        return routes.state(protocol_id, project_id)

    @router.post("/analysis/runs")
    async def start_run(body: RunIn, actor: Fresh):
        owned(actor, body.protocol_id, body.project_id)
        return await routes.start(body, actor)
