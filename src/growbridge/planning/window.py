"""The time window a stage's data belongs to."""

from growbridge.ports import StageRuntime


def data_window(stage: StageRuntime) -> tuple[float, float]:
    """``(start, end)``: the end is ``StageRuntime.window_end`` (when the stage actually ended or
    was stopped, or its planned end while it runs), the same end the freeze uses."""
    end = stage.window_end()
    if stage.started_at is None or end is None:
        raise ValueError("a stage that has not started has no data window")
    return stage.started_at, end
