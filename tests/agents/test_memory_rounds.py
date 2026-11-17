"""A project's closed rounds as a model reads them: reports, downgrades, people's decisions."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from growbridge.agents.memory_rounds import load_report, round_record, round_summaries
from growbridge.agents.memory_sources import MemorySources
from growbridge.archive.db import Database
from growbridge.archive.ids import file_digest
from growbridge.archive.models import Approval, Artifact, Snapshot
from growbridge.archive.store import Archive
from growbridge.ports import Denied
from growbridge.sim.clock import FakeClock
from growbridge.workflow.states import RoundState, StageState
from growbridge.workflow.store import RoundRow, StageRow, WorkflowStore

PROJECT, OTHER = "p-a", "p-b"


class Holdouts:
    def __init__(self, registered: dict[str, int]):
        self.registered = registered

    def holdouts(self, project_id: str) -> tuple:
        return (object(),) * self.registered.get(project_id, 0)


class World:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.clock = FakeClock()
        self.store = WorkflowStore(Database(tmp_path / "workflow.sqlite3"))
        self.archive = Archive(Database(tmp_path / "archive.sqlite3"), tmp_path / "a", self.clock)
        self.holdout = Holdouts({})
        for project in (PROJECT, OTHER):
            self.store.add_project(project, project, 0.0)

    def src(self) -> MemorySources:
        return MemorySources(
            workflow=SimpleNamespace(store=self.store),
            archive=self.archive,
            book=None,
            notes=None,
            holdout=self.holdout,
            clock=self.clock,
            timezone="UTC",
            device_id="ac5-1",
            multi_user=False,
        )

    def round(self, round_id, project=PROJECT, state=RoundState.DELIVERED, **report) -> str:
        artifact = self.report(round_id, project, **report) if report is not None else None
        row = RoundRow(
            id=round_id,
            project_id=project,
            protocol_id="proto",
            protocol_version=1,
            state=state,
            report_artifact_id=artifact,
        )
        self.clock.advance(1)
        self.store.add_round(row, self.clock.now())
        self.stage(round_id, project)
        return round_id

    def stage(self, round_id, project=PROJECT) -> str:
        stage_id = f"stage-{round_id}"
        self.store.add_stage(
            StageRow(
                stage_id=stage_id,
                round_id=round_id,
                project_id=project,
                experiment_id=f"exp-{round_id}",
                device_id="ac5-1",
                run_sheet_id=f"sheet-{round_id}",
                run_sheet_version=1,
                state=StageState.ENDED,
                state_at=self.clock.now(),
                recovery_number=0,
            )
        )
        return stage_id

    def snapshot(self, snap_id: str, experiment: str) -> str:
        snap = Snapshot(
            id=snap_id,
            experiment_id=experiment,
            version=1,
            created_at=0.0,
            manifest_sha256="0" * 64,
            complete=True,
            coverage=1.0,
        )
        self.archive.save_snapshot(snap, [f"rec-{snap_id}"])
        return snap_id

    def report(self, round_id, project=PROJECT, snapshot=None, chain=(), **fields) -> str:
        body = {
            "label": "confirmatory",
            "conclusion": "supported",
            "estimate": {"effect": 1.5, "p_value": 0.01, "blocks": 8, "estimable": True},
            "limitations": ["a", "b", "c", "d"],
            "next_round": "repeat",
            "unresolved": [],
            "evidence_chain": list(chain),
            "reasons": ["r"],
            "notes": [{"code": "n"}],
            "holdout_id": None,
            **fields,
        }
        body = {k: v for k, v in body.items() if v is not ...}
        path = self.tmp / f"report-{round_id}.json"
        path.write_text(json.dumps(body))
        artifact = Artifact(
            id=f"art-{round_id}",
            task_id=f"task-{round_id}",
            kind="research_report",
            path=str(path),
            sha256=file_digest(path),
            label="confirmatory",
            snapshot_id=snapshot,
        )
        self.archive.add_artifact(artifact)
        return artifact.id

    def approve(self, stage_id: str, at: float, voided: float | None = None) -> None:
        self.store.add_approval(
            Approval(
                id=f"appr-{stage_id}-{at}",
                run_sheet_id="sheet",
                run_sheet_version=1,
                run_sheet_digest="d",
                project_id=PROJECT,
                experiment_id="exp",
                stage_id=stage_id,
                device_id="ac5-1",
                capability_version="1",
                recovery_number=0,
                operator="alice",
                approved_at=at,
            )
        )
        if voided is not None:  # an approval is stored valid and voided later
            self.store.void_approvals(stage_id, voided)


@pytest.fixture
def world(tmp_path) -> World:
    return World(tmp_path)


def test_closed_rounds_newest_first_and_capped(world):
    for n in range(7):
        world.round(f"r{n}")
    world.round("open", state=RoundState.STAGE_RUNNING)

    found = [r["round_id"] for r in round_summaries(world.src(), PROJECT, ())]
    assert found == ["r6", "r5", "r4", "r3", "r2"]


def test_rounds_in_skip_are_left_out(world):
    world.round("r1")
    world.round("r2")

    assert [r["round_id"] for r in round_summaries(world.src(), PROJECT, {"r2"})] == ["r1"]


def test_another_projects_rounds_never_appear(world):
    world.round("mine")
    world.round("theirs", project=OTHER)

    assert [r["round_id"] for r in round_summaries(world.src(), PROJECT, ())] == ["mine"]


def test_summary_report_has_the_conclusion_and_three_limitations(world):
    world.round("r1")

    (summary,) = round_summaries(world.src(), PROJECT, ())
    assert summary["report"] == {
        "label": "confirmatory",
        "conclusion": "supported",
        "effect": 1.5,
        "p_value": 0.01,
        "limitations": ["a", "b", "c"],
        "next_round": "repeat",
        "unresolved": [],
    }


def test_invalid_report_has_no_conclusion(world):
    snap = world.snapshot("snap-a", "exp-r1")
    world.round("r1", snapshot=snap)
    world.archive.mark_dependents_invalid("rec-snap-a")

    (summary,) = round_summaries(world.src(), PROJECT, ())
    assert summary["report"] == {"invalid": True, "label": "confirmatory"}


def test_report_is_invalid_when_a_non_weakest_snapshot_is(world):
    world.stage("pre")  # gives exp-pre to this project
    a, b = world.snapshot("snap-a", "exp-r1"), world.snapshot("snap-b", "exp-pre")
    world.round("r1", snapshot=a, chain=(f"snapshot:{a}", f"snapshot:{b}"))
    world.archive.mark_dependents_invalid("rec-snap-b")

    (summary,) = round_summaries(world.src(), PROJECT, ())
    assert summary["report"] == {"invalid": True, "label": "confirmatory"}


def test_foreign_snapshots_in_the_chain_tell_nothing(world):
    world.stage("theirs", project=OTHER)
    world.snapshot("foreign-bad", "exp-theirs")
    world.snapshot("foreign-good", "exp-theirs")
    world.archive.mark_dependents_invalid("rec-foreign-bad")
    seen = []
    for n, ref in enumerate(("foreign-bad", "foreign-good", "no-such-snapshot")):
        artifact = world.report(f"r{n}", chain=(f"snapshot:{ref}",))
        downgrade, body = load_report(world.src(), PROJECT, artifact)
        seen.append((downgrade, body["conclusion"], body["estimate"]["effect"]))

    assert seen == [(None, "supported", 1.5)] * 3


def test_edited_report_is_unavailable(world):
    world.round("r1")
    path = Path(world.archive.artifact("art-r1").path)
    path.write_text(path.read_text().replace("supported", "Supported"))

    (summary,) = round_summaries(world.src(), PROJECT, ())
    assert summary["report"] == {"unavailable": True}


def test_missing_report_file_is_unavailable(world):
    world.round("r1")
    Path(world.archive.artifact("art-r1").path).unlink()

    (summary,) = round_summaries(world.src(), PROJECT, ())
    assert summary["report"] == {"unavailable": True}


def test_report_that_read_a_holdout_is_held_out(world):
    world.round("r1", holdout_id="hold-1")

    (summary,) = round_summaries(world.src(), PROJECT, ())
    assert summary["report"] == {"held_out": True, "label": "confirmatory"}


def test_old_report_in_holdout_project_is_held_out(world):
    world.round("r1", holdout_id=...)  # written before reports named their holdout
    world.round("r2", project=OTHER, holdout_id=...)
    world.holdout = Holdouts({PROJECT: 1})

    (mine,) = round_summaries(world.src(), PROJECT, ())
    (theirs,) = round_summaries(world.src(), OTHER, ())
    assert mine["report"] == {"held_out": True, "label": "confirmatory"}
    assert theirs["report"]["effect"] == 1.5


def test_a_null_holdout_in_a_holdout_project_still_shows_the_numbers(world):
    world.round("r1")
    world.holdout = Holdouts({PROJECT: 1})

    (summary,) = round_summaries(world.src(), PROJECT, ())
    assert summary["report"]["effect"] == 1.5


def test_decisions_collect_approvals_history_and_choices_newest_first(world):
    world.round("r1")
    stage = "stage-r1"
    world.approve(stage, at=10.0, voided=12.0)
    world.store.add_history(stage, 20.0, "running", "stopped", "stop", {"by": "bob", "reason": "x"})
    world.store.add_choice("r1", stage, "redo", "carol", 30.0)

    (summary,) = round_summaries(world.src(), PROJECT, ())
    assert summary["decisions"] == [
        {"at": 30.0, "kind": "choice", "choice": "redo", "by": "carol"},
        {"at": 20.0, "kind": "stop", "by": "bob", "reason": "x"},
        {"at": 10.0, "kind": "approved", "by": "alice", "voided": True},
    ]


def test_automatic_history_does_not_crowd_out_people(world):
    world.round("r1")
    stage = "stage-r1"
    world.approve(stage, at=1.0)
    world.store.add_history(stage, 2.0, "running", "stopped", "stop", {"by": "bob"})
    world.store.add_choice("r1", stage, "verify", "bob", 3.0)
    for n in range(20):
        world.store.add_history(stage, 100.0 + n, "running", "paused", "disconnect", {})

    (summary,) = round_summaries(world.src(), PROJECT, ())
    assert [d["kind"] for d in summary["decisions"]] == ["choice", "stop", "approved"]


def test_abort_appears_once(world):
    world.round("r1", state=RoundState.ABORTED)
    world.store.add_history("stage-r1", 5.0, "running", "stopped", "round_aborted", {})
    world.store.add_choice("r1", "stage-r1", "abort", "bob", 5.0)
    world.round("old", state=RoundState.ABORTED)
    world.store.add_history("stage-old", 6.0, "running", "stopped", "round_aborted", {})

    by_round = {r["round_id"]: r["decisions"] for r in round_summaries(world.src(), PROJECT, ())}
    assert by_round["r1"] == [{"at": 5.0, "kind": "choice", "choice": "abort", "by": "bob"}]
    assert by_round["old"] == [{"at": 6.0, "kind": "round_aborted", "by": None, "reason": None}]


def test_decisions_are_capped_in_summaries_but_not_in_the_record(world):
    world.round("r1")
    for n in range(12):
        world.store.add_choice("r1", "stage-r1", "redo", "bob", float(n))

    (summary,) = round_summaries(world.src(), PROJECT, ())
    record = round_record(world.src(), PROJECT, "r1")
    assert len(summary["decisions"]) == 8 and len(record["decisions"]) == 12


def test_full_view_keeps_evidence_chain_and_notes(world):
    world.round("r1", chain=("ev-1",))

    report = round_record(world.src(), PROJECT, "r1")["report"]
    assert report["evidence_chain"] == ["ev-1"]
    assert report["reasons"] == ["r"] and report["notes"] == [{"code": "n"}]
    assert report["limitations"] == ["a", "b", "c", "d"]


def test_round_of_another_project_is_unknown(world):
    world.round("theirs", project=OTHER)

    answers = []
    for round_id in ("theirs", "nothing"):
        with pytest.raises(Denied) as refused:
            round_record(world.src(), PROJECT, round_id)
        answers.append((refused.value.code, str(refused.value).replace(round_id, "<id>")))
    assert answers[0] == answers[1] == ("state", "unknown round <id>")
