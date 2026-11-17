"""The levels a run sheet plans, drawn beside the recorded levels on the environment charts."""

from datetime import datetime
from zoneinfo import ZoneInfo

from test_workbench_environment import running

from growbridge.archive.models import Channel, TimedAction
from growbridge.sim.fixtures import make_run_sheet
from growbridge.workbench.planned import planned_series
from growbridge.workflow.states import StageState

HELSINKI = ZoneInfo("Europe/Helsinki")


def local(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=HELSINKI).timestamp()


def test_planned_levels_step_at_each_local_action_time():
    sheet = make_run_sheet()  # light 60 from 06:00, off at 22:00, Europe/Helsinki
    start, end = local(2026, 5, 4, 0), local(2026, 5, 5, 0)

    series = planned_series(sheet, start, end)

    assert series["light"] == [
        (start, 0),
        (local(2026, 5, 4, 6), 60),
        (local(2026, 5, 4, 22), 0),
    ]
    assert series["exhaust"] == [(start, 30)]  # the same level all day: no extra points


def test_planned_levels_cross_midnight_from_the_previous_days_last_action():
    sheet = make_run_sheet(
        timed_actions=(
            TimedAction(id="on", channel=Channel.LIGHT, at="06:00", level=60),
            TimedAction(id="dim", channel=Channel.LIGHT, at="23:00", level=20),
        )
    )
    start, end = local(2026, 5, 4, 22), local(2026, 5, 5, 3)

    assert planned_series(sheet, start, end)["light"] == [
        (start, 60),
        (local(2026, 5, 4, 23), 20),
    ]  # still 20 after midnight, until 06:00 which is outside the span


def test_planned_levels_on_the_day_clocks_change():
    sheet = make_run_sheet()  # Europe/Helsinki; clocks go back 2026-10-25 04:00 -> 03:00
    start, end = local(2026, 10, 25, 0), local(2026, 10, 26, 0)

    light = planned_series(sheet, start, end)["light"]

    assert light == [(start, 0), (local(2026, 10, 25, 6), 60), (local(2026, 10, 25, 22), 0)]
    # 24 h later in local time is 25 real hours: an epoch-minute walk would be off by an hour
    assert local(2026, 10, 25, 22) - local(2026, 10, 25, 6) == 16 * 3600
    assert local(2026, 10, 26, 0) - start == 25 * 3600


def test_planned_levels_start_at_the_stage_start():
    sheet = make_run_sheet()
    start = local(2026, 5, 4, 12, 30)

    series = planned_series(sheet, start, local(2026, 5, 4, 13))

    assert series["light"] == [(start, 60)]


def test_a_running_stage_returns_its_plan_clipped_to_the_window(bench, operator):
    running(bench, started_at=10 * 3600.0)
    bench.clock.wall = 12 * 3600.0

    stage = operator.get("/wb/environment?window=3600").json()["stage"]

    assert stage["planned"]["light"] == [[11 * 3600.0, 60]]
    assert "pump" not in stage["planned"]


def test_planned_levels_never_start_before_the_stage_does(bench, operator):
    running(bench, started_at=11.5 * 3600.0)
    bench.clock.wall = 12 * 3600.0

    stage = operator.get("/wb/environment?window=3600").json()["stage"]

    assert stage["planned"]["light"][0][0] == 11.5 * 3600.0


def test_a_stage_that_is_not_running_has_no_plan(bench, operator):
    running(bench, started_at=0.0, state=StageState.PAUSED)
    bench.clock.wall = 12 * 3600.0

    assert operator.get("/wb/environment").json()["stage"]["planned"] == {}
