import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dev_workbench.py"


def test_dev_workbench_refuses_to_start_without_a_secret():
    env = {k: v for k, v in os.environ.items() if k != "GROWBRIDGE_DEV_SECRET"}
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60
    )
    assert result.returncode != 0 and "GROWBRIDGE_DEV_SECRET" in result.stderr


def _load_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("dev_workbench", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dev_runtime(data_dir, clock):
    from growbridge.config import Settings
    from growbridge.runtime import build_runtime
    from growbridge.sim.device import SimulatedTransport

    settings = Settings(device="SIMULATED", token="x" * 32, data_dir=data_dir)
    return build_runtime(settings, lambda _: SimulatedTransport(), clock, channels={})


def test_a_reused_data_dir_is_neither_seeded_nor_approved_again(tmp_path):
    from growbridge.sim.clock import FakeClock

    script = _load_script()
    data_dir, clock, secret = tmp_path / "data", FakeClock(), "a dev secret only"
    assert script.is_fresh(data_dir)
    first = _dev_runtime(data_dir, clock)
    script.prepare(first, secret, fresh=True)
    approved_at = first.control.safety().approved_at
    projects = first.workflow.store.db.one("SELECT COUNT(*) AS n FROM wf_projects")["n"]

    clock.advance(60)
    assert not script.is_fresh(data_dir)
    again = _dev_runtime(data_dir, clock)
    script.prepare(again, secret, fresh=script.is_fresh(data_dir))

    assert again.control.safety().approved_at == approved_at  # no second fixture approval
    assert again.workflow.store.db.one("SELECT COUNT(*) AS n FROM wf_projects")["n"] == projects


async def test_poll_status_asks_the_device_on_every_beat_and_survives_a_failure():
    script = _load_script()
    asked, beats = [], []

    async def request(method):
        asked.append(method)
        if len(asked) == 2:
            raise RuntimeError("device busy")

    async def sleep(seconds):
        beats.append(seconds)
        if len(beats) == 3:
            raise StopAsyncIteration

    try:
        await script.poll_status(request, interval=0.5, sleep=sleep)
    except StopAsyncIteration:
        pass
    assert asked == ["getDevSta"] * 3 and beats == [0.5] * 3


def test_load_roles_reads_one_role_model_per_table(tmp_path):
    script = _load_script()
    path = tmp_path / "roles.toml"
    path.write_text(
        '[planner]\nmodel = "gpt-oss:20b"\nmax_tokens = 8000\n'
        "input_per_mtok = 0\noutput_per_mtok = 0\n\n[orchestrator]\n"
    )
    roles = script.load_roles(path)
    assert set(roles) == {"planner", "orchestrator"}
    assert roles["planner"].model == "gpt-oss:20b" and roles["planner"].max_tokens == 8000
    assert roles["orchestrator"].model == "claude-opus-5-5"


def test_dev_workbench_refuses_a_roles_file_it_cannot_use(tmp_path):
    path = tmp_path / "roles.toml"
    path.write_text('[planner]\nmodel = "gpt-oss:20b"\n')  # another model must state its price
    env = {**os.environ, "GROWBRIDGE_DEV_SECRET": "a dev secret only"}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--roles", str(path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2 and "input_per_mtok" in result.stderr


async def test_recording_client_writes_each_call_and_each_failure(tmp_path):
    import json

    import pytest

    from growbridge.agents.llm import ToolCall
    from growbridge.agents.roles import PLANNER
    from growbridge.sim.llm import ScriptedClient, tool_reply

    script = _load_script()
    path = tmp_path / "calls.jsonl"
    inner = ScriptedClient([tool_reply(ToolCall(id="t1", name="validate_run_sheet", input={}))])
    ticks = iter([10.0, 12.5, 20.0, 21.0])
    client = script.RecordingClient(inner, path, clock=lambda: next(ticks))
    request = dict(
        model="gpt-oss:20b", system=PLANNER.system, tools=[{"name": "validate_run_sheet"}],
        max_tokens=256, effort="low",
    )  # fmt: skip
    first = [{"role": "user", "content": "the task"}]
    reply = await client.create(messages=first, **request)
    assert reply.tool_calls[0].name == "validate_run_sheet"
    result = {"type": "tool_result", "tool_use_id": "t1", "content": "x" * 5000}
    second = [*first, {"role": "assistant", "content": []}, {"role": "user", "content": [result]}]
    with pytest.raises(AssertionError):  # the script ran out: the failure is recorded too
        await client.create(messages=second, **request)

    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [line["role"] for line in lines] == ["planner", "planner"]
    assert lines[0]["turn"] == 1 and lines[0]["newest"] == [{"text": "the task"}]
    assert lines[0]["tool_calls"] == [{"name": "validate_run_sheet", "input": {}}]
    assert lines[0]["stop_reason"] == "tool_use" and lines[0]["seconds"] == 2.5
    assert lines[1]["turn"] == 2 and "AssertionError" in lines[1]["error"]
    clipped = lines[1]["newest"][0]["tool_result"]
    assert len(clipped) == script.TRANSCRIPT_CHARS + 1 and clipped.endswith("…")


def test_the_offset_clock_only_moves_ahead_and_keeps_what_it_skipped(tmp_path):
    script = _load_script()
    path = tmp_path / "offset"
    clock = script.OffsetClock(path)
    before = clock.now()
    clock.advance(3600)
    clock.advance(-50)  # never back
    assert clock.now() - before >= 3600 and clock.offset == 3600
    assert script.OffsetClock(path).offset == 3600  # a restart keeps the skipped time


def test_fast_forward_steps_one_sampling_interval_only_while_a_stage_runs(tmp_path):
    from growbridge.sim.clock import FakeClock
    from growbridge.workflow.states import StageState

    script = _load_script()
    clock = FakeClock()
    runtime = _dev_runtime(tmp_path / "data", clock)
    script.prepare(runtime, "a dev secret only", fresh=True)
    store = runtime.workflow.store
    assert script.fast_step(runtime) is None  # the seeded stage only waits for review
    stage = store.stage(script.STAGE_ID)
    store.update_stage(stage, state=StageState.RUNNING, started_at=clock.now())
    sheet = store.run_sheet(stage.run_sheet_id, stage.run_sheet_version)
    assert script.fast_step(runtime) == sheet.sampling.interval_seconds
    store.update_stage(store.stage(script.STAGE_ID), state=StageState.PAUSED)
    assert script.fast_step(runtime) is None  # a pause runs in real time


async def test_the_tick_loop_skips_ahead_reads_and_ticks_on_each_fast_step(monkeypatch):
    from growbridge.sim.clock import FakeClock

    script = _load_script()
    steps = iter([300.0, None])
    monkeypatch.setattr(script, "fast_step", lambda runtime: next(steps))
    seen, pauses = [], []

    class Bridge:
        async def request(self, method):
            seen.append(("read", clock.now()))

    class Runtime:
        bridge = Bridge()

        async def tick(self):
            seen.append(("tick", clock.now()))

    async def sleep(seconds):
        pauses.append(seconds)
        if len(pauses) == 2:
            raise StopAsyncIteration

    clock = FakeClock()
    start = clock.now()
    try:
        await script.tick_forever(Runtime(), clock, sleep=sleep)
    except StopAsyncIteration:
        pass
    assert seen == [("read", start + 300), ("tick", start + 300), ("tick", start + 300)]
    assert pauses == [script.FAST_PAUSE_SECONDS, script.TICK_SECONDS]


def test_the_greenhouse_moves_every_reading_with_the_light_and_the_day():
    from growbridge.sim.device import SimulatedTransport

    script = _load_script()
    sim, house = SimulatedTransport(), script.Greenhouse()
    noon, night = 12 * 3600.0, 2 * 3600.0
    seen = set()
    for n in range(20):
        house.update(sim, noon + n * 300)
        seen.add(tuple(sim.sensors[k] for k in ("temp", "humi", "co2")))
    assert len(seen) > 15  # no reading stays exactly the same: nothing looks frozen

    def mean_temp(at: float, light: int) -> float:
        sim.config["device"]["light"].update(mOnOff=int(light > 0), mLevel=light)
        values = []
        for _ in range(50):
            house.update(sim, at)
            values.append(sim.sensors["temp"])
        return sum(values) / len(values)

    assert mean_temp(noon, 70) > mean_temp(noon, 0) + 2  # the light warms the tent
    assert mean_temp(noon, 0) > mean_temp(night, 0)  # and so does the day


async def test_the_tick_loop_moves_the_readings_on_before_each_step(monkeypatch):
    from growbridge.sim.clock import FakeClock

    script = _load_script()
    steps = iter([300.0, None])
    monkeypatch.setattr(script, "fast_step", lambda runtime: next(steps))
    varied, pauses = [], []
    clock = FakeClock()
    start = clock.now()

    class Bridge:
        async def request(self, method):
            pass

    class Runtime:
        bridge = Bridge()

        def __init__(self):
            self.clock = clock

        async def tick(self):
            pass

    async def sleep(seconds):
        pauses.append(seconds)
        if len(pauses) == 2:
            raise StopAsyncIteration

    try:
        await script.tick_forever(Runtime(), clock, sleep=sleep, vary=varied.append)
    except StopAsyncIteration:
        pass
    assert varied == [start + 300, start + 300]  # the reading of each step is for its own time
