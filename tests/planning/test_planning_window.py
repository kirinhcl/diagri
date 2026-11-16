import pytest

from growbridge.agents import handlers_researcher
from growbridge.planning.window import data_window
from growbridge.ports import StageRuntime
from growbridge.sim.fixtures import make_run_sheet
from growbridge.workflow.states import StageState


def stage(**fields) -> StageRuntime:
    values = {
        "stage_id": "st1",
        "experiment_id": "e1",
        "project_id": "p1",
        "state": StageState.RUNNING,
        "run_sheet": make_run_sheet(duration_seconds=3600),
        "started_at": 1000.0,
    }
    return StageRuntime(**{**values, **fields})


def test_a_running_stage_window_runs_for_the_planned_duration():
    assert data_window(stage()) == (1000.0, 4600.0)


def test_an_ended_stage_window_ends_when_it_ended():
    assert data_window(stage(ended_at=4728.0)) == (1000.0, 4728.0)


def test_the_window_agrees_with_the_freeze():
    for current in (stage(), stage(ended_at=4728.0)):
        assert data_window(current)[1] == handlers_researcher._end(current)


def test_window_of_a_stage_not_started_is_refused():
    with pytest.raises(ValueError):
        data_window(stage(started_at=None))
