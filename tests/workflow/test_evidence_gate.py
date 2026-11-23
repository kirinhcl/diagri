"""Evidence validity at the workflow gates: submission and approval refuse a run sheet that cites
a superseded, retracted or invalid card; a stage already running is left alone."""

import pytest

from growbridge.archive.evidence_ledger import EvidenceOrigin, EvidenceRelation
from growbridge.archive.models import Channel, EvidenceCard, TimedAction
from growbridge.archive.store import Archive
from growbridge.config import Settings
from growbridge.planning.evidence_validity import GATE_CODES as BLOCKING
from growbridge.planning.evidence_validity import evidence_gate
from growbridge.ports import Denied
from growbridge.runtime import build_runtime
from growbridge.sim.clock import FakeClock
from growbridge.sim.device import SimulatedTransport
from growbridge.sim.fixtures import make_run_sheet


@pytest.fixture
def archive(db, tmp_path, clock) -> Archive:
    return Archive(db, tmp_path / "archive", clock)


@pytest.fixture(autouse=True)
def gate(world, archive):
    world.svc.validate = lambda sheet: evidence_gate(sheet, archive)


def card(card_id: str) -> EvidenceCard:
    return EvidenceCard(id=card_id, source_class="paper", citation="Doe 2020", claim="c")


def supersede(archive: Archive, old: str, new: str, at: float = 1.0) -> None:
    relation = EvidenceRelation(
        id=f"{new}-over-{old}",
        kind="supersedes",
        subject_id=new,
        object_id=old,
        reason="newer",
        source="operator:op",
        task_id=None,
        project_id=None,
        proposed_in=None,
        at=at,
    )
    archive.ledger.add_relation(relation, confirmed_by="op")


def citing(world, ref: str, **fields):
    """A sheet whose first timed action cites ``ref``."""
    base = world.sheet(**fields)
    first, *rest = base.timed_actions
    cited = first.model_copy(update={"evidence": ref})
    return base.model_copy(update={"timed_actions": (cited, *rest)})


def blocking_codes(findings) -> set[str]:
    return {f.code for f in findings if f.blocking} & BLOCKING


async def test_submitting_a_sheet_that_cites_a_superseded_card_is_refused(world, archive):
    archive.add_evidence(card("old"))
    archive.add_evidence(card("new"))
    supersede(archive, "old", "new")
    await world.design()

    findings = world.svc.submit_run_sheet(world.round_id, citing(world, "old"), world.op)

    assert blocking_codes(findings) == {"superseded_source"}
    assert world.svc.store.find_stage("stage-1") is None


async def test_approval_is_blocked_once_the_card_is_superseded_before_it(world, archive):
    archive.add_evidence(card("old"))
    archive.add_evidence(card("new"))
    await world.design()
    findings = world.svc.submit_run_sheet(world.round_id, citing(world, "old"), world.op)
    assert not any(f.blocking for f in findings)

    supersede(archive, "old", "new")

    with pytest.raises(Denied) as caught:
        world.svc.approve("stage-1", world.op)
    assert caught.value.reason == "approval_blocking_findings"


async def test_a_card_superseded_after_approval_does_not_stop_the_stage(world, archive):
    archive.add_evidence(card("old"))
    archive.add_evidence(card("new"))
    await world.design()
    world.svc.submit_run_sheet(world.round_id, citing(world, "old"), world.op)
    world.svc.approve("stage-1", world.op)

    supersede(archive, "old", "new")
    await world.svc.start_stage("stage-1", world.op)

    assert world.state() == "running"


async def test_a_new_run_sheet_for_a_running_stage_is_checked(world, archive):
    archive.add_evidence(card("old"))
    archive.add_evidence(card("new"))
    supersede(archive, "old", "new")
    await world.running()

    with pytest.raises(Denied) as caught:
        await world.svc.switch_run_sheet("stage-1", citing(world, "old", version=2), world.op)

    assert caught.value.reason == "approval_blocking_findings"
    assert world.svc.stage("stage-1").run_sheet.version == 1


async def test_another_projects_card_does_not_block_the_submission(world, archive):
    archive.add_evidence(card("theirs"))
    archive.ledger.add_origin(
        EvidenceOrigin(
            card_id="theirs",
            project_id="other-project",
            round_id="r",
            report_artifact_id="a",
            snapshot_ids=(),
            label="descriptive",
            at=0.0,
        )
    )
    await world.design()

    findings = world.svc.submit_run_sheet(world.round_id, citing(world, "theirs"), world.op)

    assert blocking_codes(findings) == set()
    assert world.state() == "pending_review"


def test_the_runtime_workflow_validates_with_the_evidence_gate(tmp_path):
    runtime = build_runtime(
        Settings(device="SIMULATED", token="x" * 32, data_dir=tmp_path / "data"),
        lambda _: SimulatedTransport(),
        FakeClock(),
    )
    try:
        runtime.archive.add_evidence(card("old"))
        runtime.archive.add_evidence(card("new"))
        supersede(runtime.archive, "old", "new")
        sheet = make_run_sheet(
            timed_actions=(
                TimedAction(id="on", channel=Channel.LIGHT, at="06:00", level=60, evidence="old"),
            )
        )

        codes = {f.code for f in runtime.workflow.validate(sheet) if f.blocking}

        assert "superseded_source" in codes
    finally:
        for db in runtime.databases:
            db.close()
