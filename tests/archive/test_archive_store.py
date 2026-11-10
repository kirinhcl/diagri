import pytest
from archive_helpers import ListSource, raw

from growbridge.archive.db import Database
from growbridge.archive.models import (
    ActionRecord,
    ActionState,
    Artifact,
    Channel,
    EvidenceCard,
    ManualMeasurement,
    RightKind,
    SampleRecord,
    Snapshot,
)
from growbridge.archive.store import Archive
from growbridge.sim.clock import START


def context(received_at):
    return ("exp-1", "veg")


def test_ingest_attributes_each_sample_by_its_own_received_time(archive):
    source = ListSource([raw(1, START), raw(2, START + 100)])

    def by_time(received_at):
        return ("exp-1", "a") if received_at < START + 50 else ("exp-2", "b")

    archive.ingest(source, "d", by_time)

    assert [(s.id, s.stage_id) for s in archive.samples("exp-1")] == [("d:1", "a")]
    assert [(s.id, s.stage_id) for s in archive.samples("exp-2")] == [("d:2", "b")]


def sample(id="d:1", at=START, **fields):
    base = dict(
        id=id,
        experiment_id="exp-1",
        stage_id="veg",
        device_id="d",
        captured_at=at,
        received_at=at,
        clock_synced=True,
        data={"t": 24.5},
    )
    return SampleRecord(**{**base, **fields})


def action(state=ActionState.PENDING, request_id="r1", **fields):
    base = dict(
        request_id=request_id,
        state=state,
        channel=Channel.LIGHT,
        planned_level=50,
        right_number=1,
        right_kind=RightKind.STAGE,
        trigger="schedule",
        created_at=START,
        experiment_id="exp-1",
    )
    return ActionRecord(**{**base, **fields})


def measurement(id="m1", value=12.5, **fields):
    base = dict(
        id=id,
        experiment_id="exp-1",
        batch="b1",
        plant_id="p1",
        layout_version="L1",
        measured_at=START,
        position="top",
        method="ruler",
        metric="height",
        value=value,
        unit="cm",
        operator="alice",
    )
    return ManualMeasurement(**{**base, **fields})


def snapshot(id="snap-1"):
    return Snapshot(
        id=id,
        experiment_id="exp-1",
        version=1,
        created_at=START,
        manifest_sha256="0" * 64,
        complete=True,
        coverage=1.0,
    )


def test_ingest_stores_records_with_stable_ids_and_context(archive):
    source = ListSource([raw(1, START), raw(2, START + 10)])

    assert archive.ingest(source, "d", context) == 2

    stored = archive.samples("exp-1")
    assert [s.id for s in stored] == ["d:1", "d:2"]
    assert stored[0].stage_id == "veg"
    assert archive.cursor("d") == 2


def test_ingest_resumes_after_restart_without_loss_or_duplicates(db, tmp_path, clock):
    source = ListSource([raw(i, START + i) for i in range(1, 6)])
    first = Archive(db, tmp_path / "a", clock)
    assert first.ingest(source, "d", context, limit=3) == 3

    restarted = Archive(db, tmp_path / "a", clock)
    assert restarted.cursor("d") == 3
    assert restarted.ingest(source, "d", context, limit=3) == 2

    assert [s.id for s in restarted.samples("exp-1")] == [f"d:{i}" for i in range(1, 6)]
    assert restarted.ingest(source, "d", context) == 0


def test_ingest_replay_of_stored_records_is_deduplicated(archive):
    source = ListSource([raw(1, START), raw(2, START + 1)])
    archive.ingest(source, "d", context)
    archive.db.execute("UPDATE ingest_cursor SET cursor = 0")  # progress record lost

    assert archive.ingest(source, "d", context) == 0

    assert len(archive.samples("exp-1")) == 2
    assert archive.cursor("d") == 2


def test_ingest_failure_keeps_records_and_cursor_together(archive):
    archive.append_sample(sample("d:2", START + 1, data={"t": 99.0}))  # conflicts with cursor 2
    source = ListSource([raw(1, START), raw(2, START + 1)])

    with pytest.raises(ValueError):
        archive.ingest(source, "d", context)

    assert archive.cursor("d") == 0
    assert [s.id for s in archive.samples("exp-1")] == ["d:2"]


def test_samples_filter_by_experiment_and_time_window(archive):
    archive.append_sample(sample("d:1", START))
    archive.append_sample(sample("d:2", START + 100))
    archive.append_sample(sample("d:3", START + 200, experiment_id="exp-2"))

    assert [s.id for s in archive.samples("exp-1", START + 50, START + 150)] == ["d:2"]
    assert [s.id for s in archive.samples("exp-1", end=START + 100)] == ["d:1", "d:2"]


def test_sample_without_capture_time_is_ordered_by_receive_time(archive):
    archive.append_sample(sample("d:1", START + 5, captured_at=None))

    assert archive.samples("exp-1", START, START + 10)[0].captured_at is None


def test_append_sample_is_idempotent_but_rejects_conflicting_rewrite(archive):
    archive.append_sample(sample())
    archive.append_sample(sample())

    assert len(archive.samples("exp-1")) == 1
    with pytest.raises(ValueError):
        archive.append_sample(sample(data={"t": 99.0}))


def test_every_action_state_change_appends_a_row(archive):
    archive.append_action(action(ActionState.PENDING))
    archive.append_action(action(ActionState.MAYBE_SENT))
    archive.append_action(action(ActionState.CONFIRMED))
    archive.append_action(action(request_id="r2", experiment_id="exp-2"))

    states = [a.state for a in archive.actions("exp-1")]
    assert states == [ActionState.PENDING, ActionState.MAYBE_SENT, ActionState.CONFIRMED]
    assert len(archive.actions()) == 4


def test_correction_is_a_new_record_and_original_is_unchanged(archive):
    archive.add_measurement(measurement("m1", 12.5))
    archive.add_measurement(measurement("m2", 13.5, corrects="m1"))

    assert [m.id for m in archive.measurements("exp-1")] == ["m2"]
    everything = archive.measurements("exp-1", include_corrected=True)
    assert [m.id for m in everything] == ["m1", "m2"]
    assert everything[0].value == 12.5


def test_correcting_unknown_measurement_is_rejected(archive):
    with pytest.raises(ValueError):
        archive.add_measurement(measurement("m2", corrects="missing"))


def test_evidence_and_artifacts_round_trip(archive):
    card = EvidenceCard(id="e1", source_class="paper", citation="X 2020", claim="more light")
    archive.add_evidence(card)
    artifact = Artifact(
        id="a1", task_id="t1", kind="report", path="r.md", sha256="0" * 64, label="exploratory"
    )
    archive.add_artifact(artifact)

    assert archive.evidence(("e1",)) == (card,)
    assert archive.evidence() == (card,)
    assert archive.evidence(("zzz",)) == ()
    assert archive.artifact("a1") == artifact
    assert archive.artifact("nope") is None
    assert archive.artifacts("t1") == (artifact,)
    assert archive.artifacts("other") == ()


def test_interventions_are_recorded_with_operator(archive):
    new_id = archive.record_intervention("exp-1", "veg", "water", {"ml": 200}, "alice")

    rows = archive.interventions("exp-1")
    assert [r["id"] for r in rows] == [new_id]
    assert rows[0]["detail"] == {"ml": 200}
    assert rows[0]["operator"] == "alice"
    assert archive.interventions("exp-2") == ()


def test_last_write_at_tracks_clock(archive, clock):
    assert archive.last_write_at() is None

    clock.advance(30)
    archive.append_sample(sample())

    assert archive.last_write_at() == clock.now()


def test_mark_dependents_invalid_flags_snapshots_and_artifacts(archive):
    archive.append_sample(sample("d:1"))
    archive.save_snapshot(snapshot("snap-1"), ["d:1"])
    archive.add_artifact(
        Artifact(
            id="a1",
            task_id="t1",
            kind="fig",
            path="f.png",
            sha256="1" * 64,
            label="exploratory",
            snapshot_id="snap-1",
        )
    )

    assert archive.mark_dependents_invalid("d:1") == ("a1", "snap-1")
    assert archive.mark_dependents_invalid("d:1") == ("a1", "snap-1")
    assert archive.is_invalid("a1") and archive.is_invalid("snap-1")
    assert archive.mark_dependents_invalid("unrelated") == ()


def test_correcting_a_measurement_invalidates_dependents(archive):
    archive.add_measurement(measurement("m1"))
    archive.save_snapshot(snapshot("snap-1"), ["m1"])

    archive.add_measurement(measurement("m2", 14.0, corrects="m1"))

    assert archive.is_invalid("snap-1")


def test_snapshots_are_listed_per_experiment_by_version(archive):
    archive.save_snapshot(snapshot("snap-1"), [])
    archive.save_snapshot(snapshot("snap-2").model_copy(update={"version": 2}), [])

    assert [s.id for s in archive.snapshots("exp-1")] == ["snap-1", "snap-2"]
    assert archive.snapshot("snap-2").version == 2
    assert archive.snapshot("missing") is None


def test_records_survive_reopening_the_database(tmp_path, clock):
    path = tmp_path / "x.db"
    first = Database(path)
    Archive(first, tmp_path / "a", clock).append_sample(sample())
    first.close()

    second = Database(path)
    try:
        assert len(Archive(second, tmp_path / "a", clock).samples("exp-1")) == 1
    finally:
        second.close()
