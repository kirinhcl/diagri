from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from growbridge.archive.models import ManualTask, TaskRecord
from growbridge.planning import manual_tasks as mt
from growbridge.sim.fixtures import make_run_sheet

ZONE = ZoneInfo("Europe/Helsinki")
START = datetime(2026, 11, 14, 8, 0, tzinfo=ZONE).timestamp()
DAY = 86400.0
TASKS = (
    ManualTask(id="water", kind="irrigation", at="09:00", seconds=5),
    ManualTask(id="photo", kind="photo", at="12:00", make_up_allowed=True),
)


def sheet(**fields):
    return make_run_sheet(timezone="Europe/Helsinki", manual_tasks=TASKS, **fields)


def record(item, outcome="done", done_at=None, recorded_at=None, **fields):
    done = item.due_at if done_at is None and outcome == "done" else done_at
    return TaskRecord(
        id=f"r-{item.task_id}-{item.due_at}-{recorded_at}",
        experiment_id="experiment-1",
        stage_id="stage-1",
        task_id=item.task_id,
        kind=item.kind,
        due_at=item.due_at,
        outcome=outcome,
        done_at=done,
        operator="op",
        recorded_at=recorded_at if recorded_at is not None else (done or item.due_at),
        **fields,
    )


def test_occurrences_follow_the_sheets_time_zone_inside_the_window():
    items = mt.occurrences(sheet(), START, START + 2 * DAY)

    assert [
        (i.task_id, datetime.fromtimestamp(i.due_at, ZONE).strftime("%d %H:%M")) for i in items
    ] == [
        ("water", "14 09:00"),
        ("photo", "14 12:00"),
        ("water", "15 09:00"),
        ("photo", "15 12:00"),
    ]
    assert items[0].seconds == 5 and items[1].make_up_allowed


def test_a_window_that_starts_after_a_tasks_time_skips_that_day():
    later = datetime(2026, 11, 14, 10, 0, tzinfo=ZONE).timestamp()

    assert [i.task_id for i in mt.occurrences(sheet(), later, later + DAY)] == ["photo", "water"]


def test_status_of_an_occurrence():
    water, photo = mt.occurrences(sheet(), START, START + DAY)
    end = START + DAY

    assert mt.status(water, None, water.due_at - 1, end) == "upcoming"
    assert mt.status(water, None, water.due_at + 60, end) == "open"
    assert mt.status(water, None, water.due_at + mt.ON_TIME_SECONDS + 1, end) == "missed"
    assert mt.status(water, record(water), end, end) == "done"
    late = record(water, done_at=water.due_at + mt.ON_TIME_SECONDS + 1)
    assert mt.status(water, late, end, end) == "late"
    assert mt.status(water, record(water, "skipped"), end, end) == "skipped"
    # a task that may be made up stays open, and done in time, until the stage ends
    assert mt.status(photo, None, photo.due_at + 5 * 3600, end) == "open"
    assert mt.status(photo, record(photo, done_at=end - 1), end, end) == "done"


def test_a_record_entered_more_than_a_day_after_the_deadline_is_late():
    """A stated done time alone cannot make an entry made long afterwards count as on time."""
    water, photo = mt.occurrences(sheet(), START, START + DAY)
    end = START + DAY
    deadline = water.due_at + mt.ON_TIME_SECONDS
    in_time = record(water, recorded_at=deadline + mt.LATE_ENTRY_SECONDS)
    a_month_later = record(water, recorded_at=water.due_at + 30 * DAY)
    made_up = record(photo, done_at=end - 1, recorded_at=end + mt.ON_TIME_SECONDS + DAY + 1)

    assert mt.status(water, in_time, end, end) == "done"
    assert mt.status(water, a_month_later, end, end) == "late"
    assert mt.status(photo, made_up, end, end) == "late"


def test_the_latest_record_of_an_occurrence_counts():
    (water, _) = mt.occurrences(sheet(), START, START + DAY)
    skipped = record(water, "skipped", recorded_at=water.due_at + 10)
    corrected = record(water, recorded_at=water.due_at + 20)

    assert mt.latest([corrected, skipped])[mt.key("water", water.due_at)] == corrected


def test_missed_counts_everything_not_done_in_time_and_the_limit():
    items = mt.occurrences(sheet(), START, START + 10 * DAY)
    end = START + 10 * DAY
    records = [record(i) for i in items if i.task_id == "photo"]
    records += [record(i) for i in items if i.task_id == "water"][:9]  # one watering missing

    missed, total, by_kind = mt.missed(items, records, end)

    assert (missed, total, by_kind) == (1, 20, {"irrigation": 1})
    assert not mt.deviates(missed, total)  # 5 % is within the limit
    assert mt.deviates(3, 20) and not mt.deviates(0, 0)
    assert mt.by_kind_text({"irrigation": 2, "photo": 1}) == "irrigation 2, photo 1"


def test_only_an_irrigation_has_a_pump_time_and_it_is_bounded():
    with pytest.raises(ValidationError):
        ManualTask(id="p", kind="photo", at="12:00", seconds=5)
    for seconds in (0, -1, 61):
        with pytest.raises(ValidationError):
            ManualTask(id="w", kind="irrigation", at="09:00", seconds=seconds)


def test_a_task_without_a_pump_time_dumps_as_before_so_old_digests_hold():
    plain = ManualTask(id="w", kind="irrigation", at="09:00")

    assert plain.model_dump(mode="json") == {
        "id": "w",
        "kind": "irrigation",
        "at": "09:00",
        "make_up_allowed": False,
    }
    assert ManualTask.model_validate(plain.model_dump()) == plain


def test_a_task_record_needs_a_time_only_when_done():
    (water, _) = mt.occurrences(sheet(), START, START + DAY)
    with pytest.raises(ValidationError):
        record(water, "skipped", done_at=water.due_at)
    with pytest.raises(ValidationError):
        TaskRecord(**{**record(water).model_dump(), "done_at": None})
