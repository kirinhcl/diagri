from growbridge.observer.frozen import FlatRun, first_change, flat_tail, sensors_used

NAN = float("nan")


def series(values, start=0.0, step=60.0):
    return [(start + i * step, v) for i, v in enumerate(values)]


def test_flat_tail_covers_the_whole_unchanged_stretch():
    assert flat_tail(series([24.0] * 121), 600) == FlatRun(24.0, 0.0, 7200.0)


def test_flat_tail_starts_after_the_last_change():
    assert flat_tail(series([23.9, 24.0, 24.0]), 600) == FlatRun(24.0, 60.0, 120.0)


def test_a_gap_longer_than_the_limit_breaks_the_run():
    run = flat_tail([(0, 24.0), (601, 24.0), (661, 24.0)], 600)
    assert run is not None
    assert run.first_at == 601.0


def test_time_going_backwards_breaks_the_run():
    run = flat_tail([(100, 24.0), (50, 24.0), (110, 24.0)], 600)
    assert run is not None
    assert run.first_at == 50.0


def test_invalid_last_point_gives_none():
    for bad in (None, NAN, float("inf"), "x", True, False, 10**400, 2**53 + 1):
        assert flat_tail([(0, 24.0), (60, bad)], 600) is None


def test_invalid_points_inside_a_run_are_skipped():
    points = [(0, 24.0), (60, None), (120, 24.0), (180, NAN), (240, 24.0)]
    assert flat_tail(points, 600) == FlatRun(24.0, 0.0, 240.0)


def test_a_long_invalid_stretch_still_breaks_the_run():
    points = [(0, 24.0)] + [(t, None) for t in range(60, 661, 60)] + [(720, 24.0)]
    run = flat_tail(points, 600)
    assert run is not None
    assert run.first_at == 720.0


def test_a_gap_equal_to_the_limit_keeps_the_run():
    assert flat_tail([(0, 24.0), (600, 24.0)], 600) == FlatRun(24.0, 0.0, 600.0)


def test_a_zero_gap_keeps_the_run():
    assert flat_tail([(100, 24.0), (100, 24.0)], 600) == FlatRun(24.0, 100.0, 100.0)


def test_a_different_valid_value_breaks_the_run_past_invalid_points():
    run = flat_tail([(0, 23.0), (60, None), (120, 24.0)], 600)
    assert run == FlatRun(24.0, 120.0, 120.0)


def test_empty_series_gives_none():
    assert flat_tail([], 600) is None


def test_first_change_skips_invalid_points():
    points = [(0, None), (60, NAN), (120, 24.0), (180, 24.1)]
    assert first_change(points, 24.0) == 180.0
    assert first_change([(0, None), (60, 24.0), (120, 24.0)], 24.0) is None


def test_sensors_used_expands_vpd():
    assert sensors_used({"vpd"}) == {"vpd", "temp", "humi"}
    assert sensors_used({"co2"}) == {"co2"}


def test_ints_and_floats_compare_equal():
    assert flat_tail(series([750, 750.0, 750]), 600) == FlatRun(750.0, 0.0, 120.0)
