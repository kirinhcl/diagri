"""Report publishing and verification (architecture doc §9.3)."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from growbridge.archive.ids import file_digest, new_id
from growbridge.archive.models import Artifact, Label, Snapshot
from growbridge.research.analysis import AnalysisDecision, Conclusion
from growbridge.research.stats import BlockEstimate
from growbridge.workflow.states import TaskState

CONCLUSION_TEXT = {"supported": "支持", "not_supported": "未获支持", "uncertain": "不确定"}


class ArtifactSink(Protocol):
    def add_artifact(self, artifact: Artifact) -> None: ...


def _effective_label(
    decision: AnalysisDecision, snapshot: Snapshot
) -> tuple[Label, tuple[str, ...]]:
    """A confirmatory label needs a complete snapshot behind it."""
    if decision.label == "confirmatory" and not snapshot.complete:
        note = f"数据快照不完整（覆盖率 {snapshot.coverage:.0%}）：不能作为确认性结果"
        return "exploratory", (note,)
    return decision.label, ()


def publish_research_report(
    sink: ArtifactSink,
    task_id: str,
    snapshot: Snapshot,
    decision: AnalysisDecision,
    estimate: BlockEstimate,
    conclusion: Conclusion,
    evidence_chain: Sequence[str],
    limitations: Sequence[str],
    next_round: str,
    unresolved: Sequence[str],
    out_dir: Path,
) -> tuple[Artifact, TaskState]:
    """Write the report, register it, and say whether it needs a human look first."""
    label, downgrade = _effective_label(decision, snapshot)
    all_limitations = (*limitations, *decision.reasons, *downgrade)
    body = {
        "task_id": task_id,
        "snapshot_id": snapshot.id,
        "label": label,
        "reasons": list(decision.reasons) + list(downgrade),
        "conclusion": conclusion,
        "conclusion_text": CONCLUSION_TEXT[conclusion],
        "estimate": estimate.model_dump(mode="json"),
        "evidence_chain": list(evidence_chain),
        "limitations": list(all_limitations),
        "next_round": next_round,
        "unresolved": list(unresolved),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_id = new_id("artifact")
    path = out_dir / f"research_report_{artifact_id}.json"
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True))
    artifact = Artifact(
        id=artifact_id,
        task_id=task_id,
        kind="research_report",
        path=str(path),
        sha256=file_digest(path),
        label=label,
        snapshot_id=snapshot.id,
        parameters={
            "effect": estimate.effect,
            "p_value": estimate.p_value,
            "conclusion": conclusion,
        },
        limitations=all_limitations,
    )
    sink.add_artifact(artifact)
    needs_review = decision.label == "confirmatory" and (bool(unresolved) or bool(downgrade))
    return artifact, TaskState.NEEDS_REVIEW if needs_review else TaskState.DONE
