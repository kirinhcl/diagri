from pathlib import Path

RUNTIME = Path(__file__).resolve().parent.parent / "src" / "growbridge" / "runtime.py"


def test_runtime_stays_within_800_lines():
    assert len(RUNTIME.read_text().splitlines()) <= 800
