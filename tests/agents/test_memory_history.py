"""The ``history`` a model task starts with: its parts, its size bound and its failure mode."""

import json
from types import SimpleNamespace

import pytest

from growbridge.agents.memory import HISTORY_CHARS, build_history, trim
from growbridge.agents.memory_sources import MemorySources
from growbridge.agents.roles import ROLES
from growbridge.archive.db import Database
from growbridge.archive.models import ActionRecord, ActionState, Channel, RightKind
from growbridge.archive.store import Archive
from growbridge.observer.alerts import AlertBook
from growbridge.observer.device_notes import DeviceNotes
from growbridge.sim.clock import FakeClock
from growbridge.workflow.states import RoundState, StageState
from growbridge.workflow.store import RoundRow, StageRow, WorkflowStore

T0 = 1_767_225_600.0  # 2026-01-01 00:00 UTC
DAY, HOUR = 86400.0, 3600.0
PROJECT = "p-a"


class World:
    def __init__(self, tmp_path):
        self.clock = FakeClock(now=T0)
        self.store = WorkflowStore(Database(tmp_path / "workflow.sqlite3"))
        self.store.run_sheet = lambda *_: SimpleNamespace(
            sampling=SimpleNamespace(max_gap_seconds=1e9)
        )
        self.archive = Archive(Database(tmp_path / "archive.sqlite3"), tmp_path / "a", self.clock)
        observer = Database(tmp_path / "observer.sqlite3")
        self.book = AlertBook(observer, self.clock)
        self.notes = DeviceNotes(observer, self.clock)
        self.store.add_project(PROJECT, PROJECT, 0.0)

    def src(self, multi_user=False) -> MemorySources:
        return MemorySources(
            workflow=SimpleNamespace(store=self.store),
            archive=self.archive,
            book=self.book,
            notes=self.notes,
            holdout=None,
            clock=self.clock,
            timezone="UTC",
            device_id="ac5-1",
            multi_user=multi_user,
        )

    def closed_round(self, round_id: str) -> None:
        row = RoundRow(
            id=round_id,
            project_id=PROJECT,
            protocol_id="proto",
            protocol_version=1,
            state=RoundState.ABORTED,
        )
        self.store.add_round(row, self.clock.now())

    def stage(self, start: float, end: float) -> None:
        self.store.add_stage(
            StageRow(
                stage_id="s1",
                round_id="r-s1",
                project_id=PROJECT,
                experiment_id="exp-s1",
                device_id="ac5-1",
                run_sheet_id="sheet",
                run_sheet_version=1,
                state=StageState.ENDED,
                started_at=start,
                state_at=end,
                recovery_number=0,
            )
        )

    def protect(self, t: float) -> None:
        self.archive.append_action(
            ActionRecord(
                request_id=f"req-{t}",
                state=ActionState.CONFIRMED,
                channel=Channel.EXHAUST,
                planned_level=100,
                right_number=1,
                right_kind=RightKind.PROTECTION,
                trigger="protect:hot",
                created_at=t,
                experiment_id="exp-s1",
                stage_id="s1",
            )
        )


@pytest.fixture
def world(tmp_path) -> World:
    return World(tmp_path)


def test_history_has_the_four_parts(world):
    world.closed_round("r1")
    world.stage(T0, T0 + 4 * DAY)
    for day in range(3):
        world.protect(T0 + day * DAY + 14 * HOUR)
    world.clock.advance(4 * DAY)
    world.notes.add("ac5-1", "alice", "changed the CO2 probe", sensor="co2")
    world.notes.add("ac5-2", "bob", "another greenhouse")

    history = json.loads(json.dumps(build_history(world.src(), PROJECT, ())))

    assert [r["round_id"] for r in history["rounds"]] == ["r1"]
    (pattern,) = [p for p in history["patterns"] if p["kind"] == "protection"]
    assert (pattern["kind"], pattern["subject"], pattern["recurring"]) == (
        "protection",
        "hot",
        True,
    )
    protected = [line for line in history["episodes"] if "protect:hot" in line]
    assert len(protected) == 3
    assert protected[0].startswith("2026-01-03 14:00")  # newest first, local time
    assert [n["text"] for n in history["notes"]] == ["changed the CO2 probe"]


def test_history_skips_rounds_already_in_the_context(world):
    world.closed_round("r1")
    world.closed_round("r2")

    history = build_history(world.src(), PROJECT, {"r2"})
    assert [r["round_id"] for r in history["rounds"]] == ["r1"]


def test_values_are_shown_when_multi_user_is_off(world):
    world.stage(T0 + 10 * HOUR, T0 + 20 * HOUR)
    world.clock.advance(3 * HOUR)
    period = world.archive.open_frozen("co2", 412.0, T0 + HOUR)  # before this project's stage
    world.clock.advance(HOUR)
    world.archive.close_frozen(period, "co2", T0 + 3 * HOUR, "value_changed")
    world.clock.advance(DAY)

    def frozen_line(multi_user):
        lines = build_history(world.src(multi_user=multi_user), PROJECT, ())["episodes"]
        (line,) = [line for line in lines if "frozen" in line]
        return line

    assert "412" in frozen_line(False) and "412" not in frozen_line(True)


def test_history_failure_does_not_stop_the_task(world, monkeypatch):
    world.closed_round("r1")
    monkeypatch.setattr(world.store, "round", lambda _id: (_ for _ in ()).throw(RuntimeError()))

    assert build_history(world.src(), PROJECT, ()) == {"error": "history unavailable"}


def big_history() -> dict:
    decision = {"at": 1.0, "kind": "stop", "by": "bob", "reason": "r" * 80}
    rounds = [
        {"round_id": f"r{n}", "report": {"conclusion": "supported"}, "decisions": [decision] * 8}
        for n in range(5)
    ]
    return {
        "rounds": rounds,
        "patterns": [{"kind": "protection", "subject": f"rule{n}", "days": 3} for n in range(10)],
        "episodes": ["2026-01-01 14:00 protect:hot exhaust -> 100" + " " * 40] * 10,
        "notes": [{"at": "2026-01-01", "by": "alice", "text": "x" * 500}] * 30,
    }


def test_trim_keeps_round_reports_last(world):
    trimmed = trim(big_history())

    text = json.dumps(trimmed, ensure_ascii=False)
    assert len(text) <= HISTORY_CHARS and json.loads(text) == trimmed
    assert trimmed["episodes"] == [] and trimmed["notes"] == []
    assert [r["report"] for r in trimmed["rounds"]] == [{"conclusion": "supported"}] * 5


def test_trim_order(world):
    history = big_history()
    history["notes"] = history["notes"][:2]
    history["rounds"] = history["rounds"][:1]
    size = len(json.dumps(history, ensure_ascii=False))
    episodes = len(json.dumps(history["episodes"], ensure_ascii=False))

    trimmed = trim(history, limit=size - episodes // 2)
    assert 0 < len(trimmed["episodes"]) < 10 and len(trimmed["notes"]) == 2

    trimmed = trim(history, limit=size - episodes - 300)
    assert trimmed["episodes"] == [] and len(trimmed["notes"]) == 1
    assert len(trimmed["rounds"][0]["decisions"]) == 8


def test_roles_tell_history_is_background():
    for role in ROLES.values():
        assert '"history"' in role.system and "background" in role.system
        assert '"invalid"' in role.system and '"held_out"' in role.system
    assert "history.rounds" in ROLES["planner"].system
