import json
from pathlib import Path

from growbridge.archive.ids import file_digest
from growbridge.archive.models import Snapshot
from growbridge.research.analysis import AnalysisDecision
from growbridge.research.report import publish_research_report
from growbridge.research.stats import BlockEstimate
from growbridge.workflow.states import TaskState


class ListSink:
    def __init__(self):
        self.artifacts = []

    def add_artifact(self, artifact):
        self.artifacts.append(artifact)


def snapshot(**overrides) -> Snapshot:
    fields = {
        "id": "snap-1",
        "experiment_id": "experiment-1",
        "version": 1,
        "created_at": 1_800_000_000.0,
        "manifest_sha256": "0" * 64,
        "complete": True,
        "coverage": 0.99,
    }
    return Snapshot(**{**fields, **overrides})


ESTIMATE = BlockEstimate(effect=1.0, blocks=8, p_value=0.01, estimable=True, note="")


def publish(
    tmp_path,
    label="confirmatory",
    unresolved=(),
    conclusion="supported",
    holdout=None,
    **snapshot_fields,
):
    sink = ListSink()
    decision = AnalysisDecision(label=label, reasons=())
    artifact, state = publish_research_report(
        sink,
        "task-1",
        snapshot(**snapshot_fields),
        decision,
        ESTIMATE,
        conclusion,
        evidence_chain=("ev-1", "ev-2"),
        limitations=("single cultivar",),
        next_round="repeat with a second cultivar",
        unresolved=unresolved,
        out_dir=tmp_path,
        **({} if holdout is None else {"holdout_id": holdout}),
    )
    return sink, artifact, state


def test_clean_confirmatory_report_is_done_and_registered(tmp_path):
    sink, artifact, state = publish(tmp_path)

    assert state is TaskState.DONE
    assert sink.artifacts == [artifact]
    assert artifact.label == "confirmatory"
    assert artifact.task_id == "task-1"
    assert artifact.snapshot_id == "snap-1"
    assert artifact.kind == "research_report"


def test_report_file_matches_the_artifact_hash_and_carries_the_required_parts(tmp_path):
    _, artifact, _ = publish(tmp_path)

    path = Path(artifact.path)
    body = json.loads(path.read_text())

    assert path.parent == tmp_path
    assert file_digest(path) == artifact.sha256
    assert body["evidence_chain"] == ["ev-1", "ev-2"]
    assert body["limitations"] == ["single cultivar"]
    assert body["next_round"] == "repeat with a second cultivar"
    assert body["estimate"]["effect"] == 1.0
    assert body["snapshot_id"] == "snap-1"


def test_confirmatory_report_with_unresolved_issues_needs_review(tmp_path):
    _, _, state = publish(tmp_path, unresolved=("两个区组缺少照片核验",))

    assert state is TaskState.NEEDS_REVIEW


def test_exploratory_report_with_unresolved_issues_is_still_done(tmp_path):
    _, artifact, state = publish(tmp_path, label="exploratory", unresolved=("open question",))

    assert state is TaskState.DONE
    assert artifact.label == "exploratory"


def test_confirmatory_label_is_downgraded_on_an_incomplete_snapshot(tmp_path):
    _, artifact, state = publish(tmp_path, complete=False, coverage=0.5)

    assert artifact.label == "exploratory"
    assert state is TaskState.NEEDS_REVIEW
    assert any("快照" in item for item in artifact.limitations)
    assert "single cultivar" in artifact.limitations


def test_the_conclusion_reaches_the_reader_and_uncertain_says_so(tmp_path):
    _, artifact, _ = publish(tmp_path, conclusion="uncertain")

    body = json.loads(Path(artifact.path).read_text())

    assert body["conclusion"] == "uncertain"
    assert body["conclusion_text"] == "不确定"
    assert artifact.parameters["conclusion"] == "uncertain"


def test_a_second_report_never_overwrites_the_first(tmp_path):
    _, first, _ = publish(tmp_path, conclusion="supported")
    _, second, _ = publish(tmp_path, conclusion="uncertain")

    assert first.path != second.path
    assert json.loads(Path(first.path).read_text())["conclusion"] == "supported"
    assert file_digest(first.path) == first.sha256


def test_report_body_names_the_holdout_it_read(tmp_path):
    _, artifact, _ = publish(tmp_path, holdout="h-1")

    assert json.loads(Path(artifact.path).read_text())["holdout_id"] == "h-1"


def test_report_body_has_a_null_holdout_without_one(tmp_path):
    _, artifact, _ = publish(tmp_path)

    body = json.loads(Path(artifact.path).read_text())
    assert "holdout_id" in body and body["holdout_id"] is None
