from datetime import date

import pytest

from growbridge.observer.metrics import compute_daily_metrics

DAY = date(2026, 11, 10)
TZ = "Europe/Helsinki"
RANGES = {"temperature": (20.0, 28.0)}


def run(samples, **kw):
    args = {"max_gap_seconds": 120.0, "ranges": RANGES}
    args.update(kw)
    return compute_daily_metrics(samples, DAY, TZ, **args)


def hour(make_sample, first, second, step=60, **fields):
    """One hour of planned samples: ``first`` for 30 minutes, then ``second``."""
    return [
        make_sample(t, {"temperature": first if t < 1800 else second}, **fields)
        for t in range(0, 3600, step)
    ]


def test_time_weighted_mean_ignores_dense_queries(make_sample):
    planned = hour(make_sample, 20.0, 30.0)
    queries = [make_sample(t, {"temperature": 40.0}, source="query") for t in range(0, 3600, 5)]

    plain = run(planned)
    with_queries = run(planned + queries)

    # the last planned sample holds one more minute, so 30 C weighs 1860 s against 1800 s
    assert plain.means["temperature"] == pytest.approx((20 * 1800 + 30 * 1860) / 3660)
    assert with_queries.means == plain.means
    assert with_queries.out_of_range_seconds == plain.out_of_range_seconds


def test_out_of_range_seconds_counts_covered_time_only(make_sample):
    metrics = run(hour(make_sample, 20.0, 30.0))

    # 30 C is above 28 C from minute 30 to the end of the held last interval (30 + 1 min)
    assert metrics.out_of_range_seconds["temperature"] == pytest.approx(1860.0)


def test_gap_truncates_interval_and_is_listed(make_sample):
    samples = [make_sample(0, {"temperature": 22.0}), make_sample(3600, {"temperature": 22.0})]

    metrics = run(samples)

    gap = next(g for g in metrics.gaps if g.start_offset == pytest.approx(120.0))
    assert gap.end_offset == pytest.approx(3600.0)
    assert metrics.coverage == pytest.approx(240.0 / 86400.0)


def test_unsynced_and_invalid_samples_are_not_counted(make_sample):
    good = hour(make_sample, 22.0, 22.0)
    bad = [
        make_sample(10, {"temperature": 99.0}, clock_synced=False),
        make_sample(20, {"temperature": 99.0}, quality="invalid"),
        make_sample(30, {"temperature": 99.0}, captured_at=None, clock_synced=False),
    ]

    assert run(good + bad).means["temperature"] == pytest.approx(22.0)


def test_samples_outside_the_local_day_are_ignored(make_sample):
    outside = [
        make_sample(-10_000, {"temperature": 99.0}),
        make_sample(86400 + 5, {"temperature": 99}),
    ]

    metrics = run(hour(make_sample, 22.0, 22.0) + outside)

    assert metrics.means["temperature"] == pytest.approx(22.0)


def test_last_sample_before_midnight_is_carried_into_the_day_when_the_gap_allows(make_sample):
    carried = [make_sample(-60, {"temperature": 30.0}), make_sample(3600, {"temperature": 20.0})]

    metrics = run(carried)

    # 30 C holds from midnight until 60 s later (max_gap 120 s minus the 60 s before midnight)
    assert metrics.out_of_range_seconds["temperature"] == pytest.approx(60.0)
    assert metrics.gaps[0].start_offset == pytest.approx(60.0)
    assert metrics.gaps[0].end_offset == pytest.approx(3600.0)


def test_sample_before_midnight_is_not_carried_across_a_longer_gap(make_sample):
    metrics = run(
        [make_sample(-120, {"temperature": 30.0}), make_sample(3600, {"temperature": 20})]
    )

    assert metrics.out_of_range_seconds["temperature"] == 0.0
    assert metrics.gaps[0].start_offset == 0.0


def test_suspect_samples_are_not_counted(make_sample):
    suspect = [make_sample(10, {"temperature": 99.0}, quality="suspect")]

    assert run(hour(make_sample, 22.0, 22.0) + suspect).means["temperature"] == pytest.approx(22.0)


def test_dli_from_ppfd_and_from_light_percent(make_sample):
    ppfd = [make_sample(t, {"ppfd": 500.0}) for t in range(0, 86400, 60)]
    percent = [make_sample(t, {"light": 50}) for t in range(0, 86400, 60)]

    from_ppfd = run(ppfd)
    from_percent = run(percent, ppfd_per_percent=10.0)

    assert from_ppfd.dli == pytest.approx(43.2, rel=1e-3)
    assert from_percent.dli == pytest.approx(43.2, rel=1e-3)
    assert run(percent).dli is None


def test_empty_day_has_zero_coverage_and_one_gap():
    metrics = run([])

    assert metrics.coverage == 0.0
    assert metrics.means == {}
    assert len(metrics.gaps) == 1
    assert metrics.date == DAY.isoformat()


def test_metrics_are_frozen(make_sample):
    metrics = run(hour(make_sample, 22.0, 22.0))
    with pytest.raises(Exception):  # noqa: B017
        metrics.coverage = 1.0
