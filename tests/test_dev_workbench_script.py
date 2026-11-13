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
