from growbridge.archive.models import SampleRecord
from growbridge.archive.readings import MAX_POINTS, bucketed_samples


def _add(archive, sample_id, at, experiment="e1", quality="ok", synced=True):
    archive.append_sample(
        SampleRecord(
            id=sample_id,
            experiment_id=experiment,
            stage_id="s1",
            device_id="d1",
            captured_at=at,
            received_at=at,
            clock_synced=synced,
            quality=quality,
            data={"temperature_c": at},
        )
    )


def test_readings_keep_one_sample_per_bucket_and_say_so(archive, db):
    for i in range(10):
        _add(archive, f"a{i}", i * 10)
    result = bucketed_samples(db, "e1", 0, 100, 5)
    assert len(result["samples"]) == 5
    assert result["total_samples"] == 10
    assert result["downsampled"]


def test_readings_count_flagged_samples_that_downsampling_drops(archive, db):
    _add(archive, "a1", 10, quality="suspect")
    _add(archive, "a2", 20, quality="ok")
    result = bucketed_samples(db, "e1", 0, 100, 1)
    (sample,) = result["samples"]
    assert sample["quality"] == "ok"
    assert sample["flagged"] == 1
    assert result["flagged_total"] == 1


def test_readings_count_unsynced_clocks_as_flagged(archive, db):
    _add(archive, "a1", 10, synced=False)
    _add(archive, "a2", 20)
    assert bucketed_samples(db, "e1", 0, 100, 600)["flagged_total"] == 1


def test_readings_leave_out_other_experiments_and_times(archive, db):
    _add(archive, "a1", 50)
    _add(archive, "a2", 500)
    _add(archive, "a3", 50, experiment="e2")
    result = bucketed_samples(db, "e1", 0, 100, 600)
    assert [s["timestamp"] for s in result["samples"]] == [50]


def test_readings_of_an_empty_window_are_empty(archive, db):
    result = bucketed_samples(db, "e1", 0, 100, 600)
    assert result["samples"] == [] and result["total_samples"] == 0 and not result["downsampled"]


def test_readings_clamp_points_to_the_allowed_range(archive, db):
    _add(archive, "a1", 50)
    low = bucketed_samples(db, "e1", 0, 10000, 0)
    assert low["window"]["bucket_seconds"] == 5000
    high = bucketed_samples(db, "e1", 0, 10000, 5000)
    assert high["window"]["bucket_seconds"] == 10000 / MAX_POINTS


def test_readings_of_a_reversed_window_are_empty(archive, db):
    _add(archive, "a1", 50)
    for start, end in ((100, 0), (50, 50)):
        result = bucketed_samples(db, "e1", start, end, 600)
        assert result["samples"] == [] and result["total_samples"] == 0
        assert result["flagged_total"] == 0 and not result["downsampled"]
        assert set(result["window"]) == {"start", "end", "bucket_seconds"}
