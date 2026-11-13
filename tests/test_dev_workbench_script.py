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
