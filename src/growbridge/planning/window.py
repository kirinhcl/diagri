"""The time window a stage's data belongs to."""

from growbridge.ports import StageRuntime


def data_window(stage: StageRuntime) -> tuple[float, float]:
    """``(start, end)``: the end is when the stage actually ended or was stopped, or its planned
    end while it runs. The same end the freeze uses."""
    if stage.started_at is None:
        raise ValueError("a stage that has not started has no data window")
    end = stage.ended_at
    if end is None:
        end = stage.started_at + stage.run_sheet.duration_seconds
    return stage.started_at, end
