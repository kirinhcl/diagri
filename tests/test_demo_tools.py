"""The demo recording tools in scripts/demo: the editor's cut plan and the on-site helper."""

import importlib.util
import json
import random
import sys
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parents[1] / "scripts" / "demo"

# 0-2 s blank (cut); 20-60 s a model wait squeezed to 4 s; 70-71 s a wait already shorter than
# its target, which stays at real speed.
TIMELINE = {
    "duration": 100.0,
    "marks": [
        {"type": "cut", "start": 0.0, "end": 2.0},
        {"type": "speed", "start": 20.0, "end": 60.0, "target": 4.0},
        {"type": "speed", "start": 70.0, "end": 71.0, "target": 4.0},
    ],
    "chapters": [{"t": 2.5, "title": "intro"}, {"t": 65.0, "title": "Chapter 1"}],
}


def _load(name):
    spec = importlib.util.spec_from_file_location(f"demo_{name}", DEMO / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def edit():
    return _load("edit")


@pytest.fixture(scope="module")
def helper():
    return _load("onsite_helper")


def test_plan_squeezes_time_lapses_and_drops_cuts(edit):
    pieces = edit.plan(TIMELINE)

    spans = [(p["start"], p["end"], p["speed"]) for p in pieces]
    assert spans == [
        (2.0, 20.0, 1.0),
        (20.0, 60.0, 10.0),
        (60.0, 70.0, 1.0),
        (70.0, 71.0, 1.0),
        (71.0, 100.0, 1.0),
    ]
    assert sum(edit.length(p) for p in pieces) == pytest.approx(18 + 4 + 10 + 1 + 29)


def test_holds_split_real_speed_pieces_and_shift_later_times(edit):
    pieces = edit.insert_holds(edit.plan(TIMELINE), [{"t": 65.0, "seconds": 5}])

    assert [p["kind"] for p in pieces] == ["play", "play", "play", "hold", "play", "play", "play"]
    assert edit.to_output(65.0, pieces) == pytest.approx(18 + 4 + 5)
    assert edit.to_output(80.0, pieces) == pytest.approx(18 + 4 + 5 + 5 + 5 + 1 + 9)


def test_a_hold_inside_a_time_lapse_is_refused(edit):
    with pytest.raises(ValueError, match="time-lapse"):
        edit.insert_holds(edit.plan(TIMELINE), [{"t": 30.0, "seconds": 3}])


def test_a_hold_outside_the_kept_recording_is_refused(edit):
    with pytest.raises(ValueError, match="outside"):
        edit.insert_holds(edit.plan(TIMELINE), [{"t": 1.0, "seconds": 3}])


def test_chapters_start_at_zero_and_follow_the_edit(edit):
    pieces = edit.plan(TIMELINE)

    marks = edit.chapters(TIMELINE, pieces, total=62.0)

    assert marks[0] == (0.0, edit.FIRST_CHAPTER)
    assert marks[1] == (pytest.approx(18 + 4 + 5), "Chapter 1")


def test_a_due_task_is_recorded_at_its_due_time(helper):
    assert helper.done_at_for(due_at=1000.0, now=1500.0) == 1000.0


def test_a_task_open_before_its_due_time_is_recorded_now(helper):
    assert helper.done_at_for(due_at=1000.0, now=400.0) == 400.0


class FakeClient:
    """Answers the helper's reads from fixed data and keeps every POST it is sent."""

    def __init__(self, occurrences, now=2000.0):
        self.listing = {"now": now, "occurrences": occurrences}
        self.posts = []

    def get(self, path):
        if path.endswith("/manual-tasks"):
            return self.listing
        return {"stage_id": "stage-x", "experiment_id": "exp-x", "started_at": 0.0}

    def post(self, path, body):
        self.posts.append((path, body))
        return {}


def _occurrence(task_id, kind, due_at, status):
    return {"task_id": task_id, "kind": kind, "due_at": due_at, "status": status}


def test_the_helper_records_open_and_late_tasks_once(helper, tmp_path):
    client = FakeClient(
        [
            _occurrence("measure-canopy-0915", "measurement", 1800.0, "open"),
            _occurrence("irrigation-0800", "irrigation", 1000.0, "late"),
            _occurrence("photo-0900", "photo", 5000.0, "upcoming"),
            _occurrence("photo-0900", "photo", 900.0, "done"),
        ]
    )
    worker = helper.Helper(client, tmp_path / "helper.jsonl")

    worker.step("stage-x")
    worker.step("stage-x")  # the same occurrences again: nothing new is sent

    tasks = [body for path, body in client.posts if path.endswith("/manual-tasks")]
    assert [(t["task_id"], t["done_at"]) for t in tasks] == [
        ("measure-canopy-0915", 1800.0),
        ("irrigation-0800", 1000.0),
    ]
    assert tasks[1]["note"] == helper.WATER_NOTE


def test_a_measurement_task_brings_one_simulated_value_per_plant(helper, tmp_path):
    client = FakeClient([_occurrence("measure-canopy-0915", "measurement", 1800.0, "open")])
    worker = helper.Helper(client, tmp_path / "helper.jsonl")

    worker.step("stage-x")

    values = [body for path, body in client.posts if path == "/wb/measurements"]
    assert [v["plant_id"] for v in values] == [f"plant-{i}" for i in range(1, helper.PLANTS + 1)]
    assert {v["metric"] for v in values} == {"canopy_area_growth"}
    assert {v["measured_at"] for v in values} == {1800.0}
    assert all("simulated" in v["method"] and v["experiment_id"] == "exp-x" for v in values)


def test_chapter_metadata_ends_each_chapter_where_the_next_begins(edit, tmp_path):
    meta = tmp_path / "chapters.ffmeta"

    edit.write_metadata(meta, [(0.0, "intro"), (12.5, "Chapter 1")], total=30.0)

    text = meta.read_text()
    assert text.startswith(";FFMETADATA1")
    assert "START=0\nEND=12500\ntitle=intro" in text
    assert "START=12500\nEND=30000\ntitle=Chapter 1" in text
    assert edit.stamp(387.9) == "06:27"


def test_the_editor_encodes_each_piece_and_joins_them_with_chapters(edit, tmp_path, monkeypatch):
    (tmp_path / "timeline.json").write_text(json.dumps(TIMELINE))
    holds = tmp_path / "holds.json"
    holds.write_text(json.dumps([{"t": 65.0, "seconds": 5, "label": "read"}]))
    commands = []
    monkeypatch.setattr(edit, "run", commands.append)
    out = tmp_path / "final.mp4"
    argv = ["edit.py", str(tmp_path), "--ffmpeg", "ff", "--holds", str(holds), "--out", str(out)]
    monkeypatch.setattr(sys, "argv", argv)

    assert edit.main() == 0

    plays, hold = 6, 1  # five pieces, one of them split by the hold
    assert len(commands) == plays + 2 * hold + 1  # a hold is one still frame plus its encode
    assert any("-frames:v" in c and "65.000" in c for c in commands)
    assert commands[-1][-1] == str(out) and "-map_chapters" in commands[-1]
    # The chapter at raw 65 s opens at 18 + 4 + 5 = 27 s, before the hold placed at the same time.
    assert (tmp_path / "chapters.txt").read_text().splitlines()[1] == "00:27  Chapter 1"


def test_a_failed_ffmpeg_call_raises_with_its_message(edit):
    failing = [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"]

    with pytest.raises(RuntimeError, match="boom"):
        edit.run(failing)


def test_the_helper_watches_only_running_stages(helper):
    class Rounds:
        def get(self, path):
            if path == "/wb/projects":
                return {"projects": [{"latest_round": {"round_id": "r1"}}, {"latest_round": None}]}
            stages = [{"stage_id": "s1", "state": "running"}, {"stage_id": "s0", "state": "ended"}]
            return {"stages": stages}

    assert helper.running_stages(Rounds()) == ["s1"]


def test_the_helper_refuses_to_start_without_a_secret(helper, tmp_path, monkeypatch):
    monkeypatch.delenv(helper.SECRET_VARIABLE, raising=False)
    monkeypatch.setattr(sys, "argv", ["onsite_helper.py", "--log", str(tmp_path / "h.jsonl")])

    assert helper.main() == 2


def test_a_refused_record_is_logged_and_not_retried(helper, tmp_path):
    class Refusing(FakeClient):
        def post(self, path, body):
            super().post(path, body)
            raise RuntimeError("POST refused: 409 state")

    client = Refusing([_occurrence("photo-0900", "photo", 900.0, "open")])
    log = tmp_path / "helper.jsonl"
    worker = helper.Helper(client, log)

    worker.step("stage-x")
    worker.step("stage-x")

    assert len(client.posts) == 1
    assert "409 state" in json.loads(log.read_text().splitlines()[0])["error"]


@pytest.fixture
def workbench_stub():
    """A local HTTP server standing in for the workbench: login sets a cookie, reads need it."""
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, code, body, cookie=None):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):  # noqa: N802 (http.server's name)
            self.rfile.read(int(self.headers["Content-Length"]))
            if self.path == "/wb/login":
                self._send(200, {"operator": "dev"}, cookie="growbridge_operator=t; Path=/wb")
            else:
                self._send(409, {"detail": {"code": "state"}})

        def do_GET(self):  # noqa: N802
            signed_in = "growbridge_operator=t" in (self.headers.get("Cookie") or "")
            self._send(200 if signed_in else 401, {"projects": []})

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_the_client_signs_in_keeps_the_cookie_and_reports_refusals(
    helper, workbench_stub, monkeypatch
):
    monkeypatch.setattr(helper, "BASE", workbench_stub)

    client = helper.Client("a-test-secret-value")

    assert client.get("/wb/projects") == {"projects": []}
    with pytest.raises(RuntimeError, match="409"):
        client.post("/wb/stages/s1/manual-tasks", {"task_id": "photo-0900"})


def test_still_intervals_are_read_from_freezedetect_and_shifted_to_raw_time(monkeypatch):
    stills = _load("find_stills")
    stderr = (
        "[freezedetect @ 0x1] lavfi.freezedetect.freeze_start: 0.12\n"
        "[freezedetect @ 0x1] lavfi.freezedetect.freeze_duration: 1.56\n"
        "[freezedetect @ 0x1] lavfi.freezedetect.freeze_end: 1.68\n"
        "[freezedetect @ 0x1] lavfi.freezedetect.freeze_start: 3.76\n"  # still at the window's end
    )
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return type("Done", (), {"stderr": stderr})()

    monkeypatch.setattr(stills.subprocess, "run", fake_run)

    found = stills.stills("ff", "raw.mp4", 824.0, 849.0)

    assert found == [(pytest.approx(824.12), pytest.approx(825.68)), (pytest.approx(827.76), 849.0)]
    assert seen["cmd"][seen["cmd"].index("-ss") + 1] == "824.0"


def test_growth_values_are_reproducible_and_rise_over_the_stage(helper):
    first = [helper.growth_value(random.Random(1), 1.0, day) for day in (0, 20)]
    again = [helper.growth_value(random.Random(1), 1.0, day) for day in (0, 20)]

    assert first == again
    assert first[1] > first[0] > 0
