"""The pre-registration rule of a confirmatory run (architecture §6.5).

A confirmatory result needs an analysis that was fixed before the outcome data existed. So a
snapshot may be analysed confirmatorily only if all of its data was collected at or after the
moment the analysis script was frozen: every stage behind it started then or later, and every
manual measurement in it was recorded then or later. Data collected earlier can never be
confirmatory, whatever the rounds or protocol versions say.

Stage times come from the workflow store. The time a measurement was *recorded* comes from the
archive's own clock, never from ``measured_at``: that field is typed in by the operator.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

from growbridge.archive.models import ManualMeasurement
from growbridge.ports import Denied

RecordedAt = Callable[[Sequence[str]], Mapping[str, float | None]]
RULE = "data collected before the analysis script was frozen can never be confirmatory"


def require_stages_after(
    frozen_at: float, snapshot_id: str, stage_starts: Iterable[float | None]
) -> None:
    """Refuse when a stage behind the snapshot started before the freeze. A stage that has not
    started has produced nothing; its manual measurements are checked separately."""
    if any(started is not None and started < frozen_at for started in stage_starts):
        raise Denied(
            "state",
            f"snapshot {snapshot_id} holds data of a stage that started before the analysis "
            f"script was frozen: {RULE}",
        )


def require_measurements_after(
    frozen_at: float, snapshot_id: str, measurements: Path, recorded_at: RecordedAt
) -> None:
    """Refuse when a manual measurement in the snapshot was recorded before the freeze (or when
    no recording time is known: it predates the archive keeping one). Quotes no value."""
    ids = []
    for line in measurements.read_text(encoding="utf-8").splitlines():
        if line:
            ids.append(ManualMeasurement.model_validate_json(line).id)
    times = recorded_at(ids)
    if any(times.get(ident) is None or times[ident] < frozen_at for ident in ids):
        raise Denied(
            "state",
            f"snapshot {snapshot_id} holds a measurement recorded before the analysis script "
            f"was frozen: {RULE}",
        )
