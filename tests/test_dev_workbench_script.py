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
