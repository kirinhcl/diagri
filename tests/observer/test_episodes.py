"""Environment episodes (protection writes, frozen periods, data gaps) and recurring patterns."""

from types import SimpleNamespace

import pytest

from growbridge.archive.db import Database
from growbridge.archive.models import (
    ActionRecord,
    ActionState,
    Channel,
    RightKind,
    SampleRecord,
)
from growbridge.archive.store import Archive
from growbridge.observer.alerts import AlertBook
from growbridge.observer.episodes import (
    Episode,
    patterns,
    project_episodes,
    recurring_lines,
    stage_windows,
)
from growbridge.observer.metrics import compute_daily_metrics, coverage_gaps
from growbridge.ports import Actor
from growbridge.sim.clock import FakeClock
from growbridge.workflow.states import StageState
from growbridge.workflow.store import StageRow, WorkflowStore

T0 = 1_767_225_600.0  # 2026-01-01 00:00 UTC
DAY, HOUR, MINUTE = 86400.0, 3600.0, 60.0
PROJECT, OTHER = "p-a", "p-b"
ALICE = Actor(kind="operator", id="alice")


class World:
    def __init__(self, tmp_path):
        self.clock = FakeClock(now=T0)
        self.store = WorkflowStore(Database(tmp_path / "workflow.sqlite3"))
        self.store.run_sheet = lambda *_: SimpleNamespace(
            sampling=SimpleNamespace(max_gap_seconds=600.0)
        )
        self.archive = Archive(Database(tmp_path / "archive.sqlite3"), tmp_path / "a", self.clock)
        self.book = AlertBook(Database(tmp_path / "observer.sqlite3"), self.clock)
        self.seq = 0

    def at(self, t: float) -> None:
        self.clock.advance(t - self.clock.now())

    def stage(self, name, start, end=None, project=PROJECT) -> str:
        finished = end is not None
        self.store.add_stage(
            StageRow(
                stage_id=name,
                round_id=f"r-{name}",
                project_id=project,
                experiment_id=f"exp-{name}",
                device_id="ac5-1",
                run_sheet_id="sheet",
                run_sheet_version=1,
                state=StageState.ENDED if finished else StageState.RUNNING,
                started_at=start,
                state_at=end if finished else start,
                recovery_number=0,
            )
        )
        return name

    def protect(self, stage, t, rule="hot", level=100) -> None:
        self.seq += 1
        self.archive.append_action(
            ActionRecord(
                request_id=f"req-{self.seq}",
                state=ActionState.CONFIRMED,
                channel=Channel.EXHAUST,
                planned_level=level,
                right_number=1,
                right_kind=RightKind.PROTECTION,
                trigger=f"protect:{rule}",
                created_at=t,
                experiment_id=f"exp-{stage}",
                stage_id=stage,
            )
        )

    def frozen(self, sensor, first, opened, last=None, closed=None, value=400.0) -> str:
        self.at(opened)
        period = self.archive.open_frozen(sensor, value, first)
        if closed is not None:
            self.at(closed)
            self.archive.close_frozen(period, sensor, last, "value_changed")
        return period

    def sample(self, stage, t, **fields) -> None:
        self.seq += 1
        record = SampleRecord(
            id=f"s-{self.seq}",
            experiment_id=f"exp-{stage}",
            stage_id=stage,
            device_id="ac5-1",
            captured_at=t,
            received_at=t,
            clock_synced=fields.pop("clock_synced", True),
            data={"temp": 22.0},
            **fields,
        )
        self.archive.append_sample(record)

    def episodes(self, now, since=None, hide=False) -> list[Episode]:
        since = now - 7 * DAY if since is None else since
        return project_episodes(
            self.store, self.archive, self.book, PROJECT, since, now, hide_values=hide
        )


@pytest.fixture
def world(tmp_path) -> World:
    return World(tmp_path)


def protections(found):
    return [e for e in found if e.kind == "protection"]


# --- protection -----------------------------------------------------------------------------


def test_protection_writes_merge_within_fifteen_minutes(world):
    world.stage("s1", T0)
    for t in (T0 + 14 * HOUR, T0 + 14 * HOUR + 10 * MINUTE, T0 + 14 * HOUR + 40 * MINUTE):
        world.protect("s1", t)
    world.protect("s1", T0 + 14 * HOUR + 5 * MINUTE, rule="cold")

    found = protections(world.episodes(T0 + DAY))
    assert [(e.subject, e.start) for e in found] == [
        ("hot", T0 + 14 * HOUR),
        ("cold", T0 + 14 * HOUR + 5 * MINUTE),
        ("hot", T0 + 14 * HOUR + 40 * MINUTE),
    ]
    assert found[0].end is None and found[0].detail == {"channel": "exhaust", "level": 100}


def test_protection_outside_the_projects_stages_is_left_out(world):
    world.stage("mine", T0, T0 + HOUR)
    world.stage("theirs", T0 + 2 * HOUR, project=OTHER)
    world.protect("mine", T0 + 30 * MINUTE)
    world.protect("mine", T0 + 90 * MINUTE)  # after the stage ended
    world.protect("theirs", T0 + 3 * HOUR)

    assert [e.start for e in protections(world.episodes(T0 + DAY))] == [T0 + 30 * MINUTE]


# --- frozen ---------------------------------------------------------------------------------


def test_frozen_uses_the_first_flat_sample(world):
    world.stage("s1", T0)
    world.frozen(
        "co2", first=T0 + HOUR, opened=T0 + 3 * HOUR, last=T0 + 5 * HOUR, closed=T0 + 5 * HOUR + 300
    )

    (ep,) = [e for e in world.episodes(T0 + DAY) if e.kind == "frozen"]
    assert (ep.subject, ep.start, ep.end, ep.in_project) == ("co2", T0 + HOUR, T0 + 5 * HOUR, True)
    assert ep.detail == {"value": 400.0}


def test_open_frozen_has_no_duration(world):
    world.stage("s1", T0)
    for day in range(3):
        start = T0 + day * DAY + 14 * HOUR
        world.frozen(
            "co2",
            first=start,
            opened=start + 2 * HOUR,
            last=start + 3 * HOUR,
            closed=start + 3 * HOUR + 60,
        )
    world.frozen("co2", first=T0 + 3 * DAY + 14 * HOUR, opened=T0 + 3 * DAY + 16 * HOUR)

    found = world.episodes(T0 + 3 * DAY + 20 * HOUR)
    assert [e for e in found if e.kind == "frozen"][-1].end is None
    (pattern,) = [p for p in patterns(found, T0 + 3 * DAY + 20 * HOUR, "UTC") if p.kind == "frozen"]
    assert pattern.typical_minutes == 180.0 and pattern.days == 4


def test_frozen_outside_the_project_hides_its_value_when_asked(world):
    world.stage("s1", T0 + 10 * HOUR)
    world.frozen(
        "co2", first=T0 + HOUR, opened=T0 + 3 * HOUR, last=T0 + 4 * HOUR, closed=T0 + 4 * HOUR + 60
    )

    (hidden,) = [e for e in world.episodes(T0 + DAY, hide=True) if e.kind == "frozen"]
    (shown,) = [e for e in world.episodes(T0 + DAY, hide=False) if e.kind == "frozen"]
    assert hidden.in_project is False and hidden.detail == {}
    assert shown.detail == {"value": 400.0}


def test_frozen_carries_the_read_note_of_its_alert(world):
    world.stage("s1", T0)
    # the last flat sample is at 14:00; the check sees it at 14:05 and raises the alert
    period = world.frozen("co2", first=T0 + 12 * HOUR, opened=T0 + 14 * HOUR + 5 * MINUTE)
    alert = world.book.raise_alert("frozen_reading", "co2", "warning", "flat")
    other = world.book.raise_alert("frozen_reading", "temp", "warning", "flat")
    world.book.mark_read(alert.event_id, ALICE, note="wire loose")
    world.book.mark_read(other.event_id, ALICE, note="not this one")
    world.at(T0 + 14 * HOUR + 20 * MINUTE)
    world.archive.close_frozen(period, "co2", T0 + 14 * HOUR, "value_changed")
    world.book.resolve("frozen_reading", "co2")

    (ep,) = [e for e in world.episodes(T0 + DAY) if e.kind == "frozen"]
    assert ep.notes == ("wire loose",)


# --- gaps -----------------------------------------------------------------------------------


def test_gaps_shorter_than_thirty_minutes_are_dropped(world):
    world.stage("s1", T0, T0 + 4 * HOUR)
    for t in range(0, 4 * 3600, 300):
        if not (HOUR <= t < HOUR + 20 * MINUTE or 2 * HOUR <= t < 3 * HOUR):
            world.sample("s1", T0 + t)

    gaps = [(e.start, e.end) for e in world.episodes(T0 + DAY) if e.kind == "data_gap"]
    assert gaps == [(T0 + 2 * HOUR - 5 * MINUTE + 600, T0 + 3 * HOUR)]


def test_query_unsynced_and_bad_samples_do_not_cover_a_gap(world):
    world.stage("s1", T0, T0 + 2 * HOUR)
    for t in range(0, 2 * 3600, 300):
        inside = HOUR <= t < HOUR + 40 * MINUTE
        kind = ({"source": "query"}, {"clock_synced": False}, {"quality": "suspect"})[t // 300 % 3]
        world.sample("s1", T0 + t, **(kind if inside else {}))

    gaps = [e for e in world.episodes(T0 + DAY) if e.kind == "data_gap"]
    assert len(gaps) == 1 and gaps[0].end - gaps[0].start >= 30 * MINUTE


def test_gaps_read_only_the_last_seven_days(world, monkeypatch):
    world.stage("old", T0, T0 + DAY)
    world.stage("across", T0 + 20 * DAY, T0 + 30 * DAY)
    calls = []
    real = world.archive.samples
    monkeypatch.setattr(
        world.archive, "samples", lambda exp, a, b: calls.append((exp, a, b)) or real(exp, a, b)
    )

    now = T0 + 31 * DAY
    world.episodes(now)
    assert calls == [("exp-across", now - 7 * DAY, T0 + 30 * DAY)]


# --- cutoff ---------------------------------------------------------------------------------


def test_nothing_after_now_is_used(world):
    world.stage("s1", T0, T0 + 3 * DAY)
    world.frozen(
        "co2",
        first=T0 + HOUR,
        opened=T0 + 3 * HOUR,
        last=T0 + 30 * HOUR,
        closed=T0 + 30 * HOUR + 60,
    )
    world.protect("s1", T0 + 10 * HOUR)
    world.protect("s1", T0 + 30 * HOUR)
    now = T0 + DAY

    found = world.episodes(now)
    (frozen,) = [e for e in found if e.kind == "frozen"]
    assert frozen.end is None
    assert [e.start for e in protections(found)] == [T0 + 10 * HOUR]
    assert stage_windows(world.store, PROJECT, now)[0][:2] == (T0, now)


def test_frozen_detected_after_now_is_left_out(world):
    world.stage("s1", T0)
    world.frozen("co2", first=T0 + 23 * HOUR, opened=T0 + DAY + HOUR)

    assert [e for e in world.episodes(T0 + DAY) if e.kind == "frozen"] == []


# --- patterns -------------------------------------------------------------------------------


def ep(start, end=None, kind="protection", subject="hot") -> Episode:
    return Episode(kind=kind, subject=subject, start=start, end=end, in_project=True, detail={})


def test_three_days_near_the_same_hour_recur(world):
    found = [ep(T0 + d * DAY + 14 * HOUR + d * 600) for d in range(3)]

    (pattern,) = patterns(found, T0 + 4 * DAY, "UTC")
    assert (pattern.days, pattern.recurring, pattern.typical_start) == (3, True, "14:10")
    assert pattern.last == "2026-01-03" and pattern.typical_minutes is None
    assert recurring_lines([pattern]) == ("protect:hot on 3 of the last 7 days, around 14:10",)


def test_two_days_do_not_recur(world):
    found = [ep(T0 + d * DAY + 14 * HOUR) for d in range(2)]

    assert patterns(found, T0 + 4 * DAY, "UTC")[0].recurring is False


def test_scattered_starts_do_not_recur(world):
    found = [ep(T0 + d * DAY + h * HOUR) for d, h in ((0, 2), (1, 9), (2, 18))]

    assert patterns(found, T0 + 4 * DAY, "UTC")[0].recurring is False


def test_starts_across_midnight_cluster(world):
    # 1 Jan 23:30, 3 Jan 00:10, 4 Jan 23:50: three days, one time slot around midnight
    found = [
        ep(T0 + 23 * HOUR + 30 * MINUTE),
        ep(T0 + 2 * DAY + 10 * MINUTE),
        ep(T0 + 3 * DAY + 23 * HOUR + 50 * MINUTE),
    ]

    (pattern,) = patterns(found, T0 + 6 * DAY, "UTC")
    assert pattern.recurring is True and pattern.typical_start in {"23:30", "23:50", "00:10"}


def test_back_to_back_episodes_count_once(world):
    found = [
        ep(T0 + 23 * HOUR, T0 + DAY, kind="frozen", subject="co2"),
        ep(T0 + DAY + 5 * MINUTE, T0 + DAY + 2 * HOUR, kind="frozen", subject="co2"),
    ]

    (pattern,) = patterns(found, T0 + 3 * DAY, "UTC")
    assert pattern.days == 1 and pattern.typical_minutes == 180.0


def test_only_the_last_seven_days_and_started_before_now_count(world):
    found = [ep(T0 - 8 * DAY), ep(T0 + HOUR), ep(T0 + 2 * DAY)]

    (pattern,) = patterns(found, T0 + DAY, "UTC")
    assert pattern.days == 1


def test_recurring_patterns_come_first(world):
    found = [ep(T0 + d * DAY + 14 * HOUR) for d in range(3)]
    found += [
        ep(T0 + d * DAY + h * HOUR, subject="cold") for d, h in ((0, 1), (1, 6), (2, 12), (3, 18))
    ]

    assert [p.subject for p in patterns(found, T0 + 5 * DAY, "UTC")] == ["hot", "cold"]


# --- metrics stay as they were -------------------------------------------------------------


def test_coverage_gaps_are_absolute_and_daily_metrics_unchanged(world):
    from datetime import date

    world.stage("s1", T0, T0 + DAY)
    for t in range(0, 24 * 3600, 300):
        if not (HOUR <= t < 2 * HOUR):
            world.sample("s1", T0 + t)
    samples = world.archive.samples("exp-s1")

    assert coverage_gaps(samples, T0, T0 + DAY, 600.0) == ((T0 + HOUR - 300 + 600, T0 + 2 * HOUR),)
    metrics = compute_daily_metrics(samples, date(2026, 1, 1), "UTC", 600.0, {})
    assert [(g.start_offset, g.end_offset) for g in metrics.gaps] == [(HOUR + 300, 2 * HOUR)]
