"""The server's message code registry (growbridge.codes) and its export for the console
(tests/web/fixtures/message-codes.json). Later tasks check their emission sites with
codes_at_calls."""

import ast
import json
import logging
from pathlib import Path

import pytest

import growbridge
from growbridge import codes
from growbridge.codes import CODES, Code, checked

REPO = Path(__file__).resolve().parents[2]
# The registry is checked as this checkout ships it, not another install of growbridge.
assert Path(growbridge.__file__).resolve().is_relative_to(REPO / "src"), (
    f"imported growbridge from {growbridge.__file__}, not {REPO / 'src'}: run with PYTHONPATH=src"
)
EXPORTED = REPO / "tests" / "web" / "fixtures" / "message-codes.json"
FAMILIES = {
    "alert",
    "finding",
    "receipt",
    "task_end",
    "compute_error",
    "compute_stuck",
    "chat_end",
    "estimate",
}


def codes_at_calls(root: Path, names: set[str]) -> list[tuple[str, int, str]]:
    """(file, line, code) for each call of a function in ``names`` with a literal ``code=``."""
    found: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if called not in names:
                continue
            for item in node.keywords:
                value = item.value
                if (
                    item.arg == "code"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    found.append((str(path), node.lineno, value.value))
    return found


def test_the_console_list_matches_the_registry() -> None:
    on_disk = json.loads(EXPORTED.read_text(encoding="utf-8"))
    assert on_disk == codes.export(), "run: PYTHONPATH=src python scripts/export_message_codes.py"


def test_the_families_are_fixed() -> None:
    assert set(CODES) == FAMILIES


def test_checked_logs_an_unregistered_code_and_keeps_the_params(
    caplog: pytest.LogCaptureFixture,
) -> None:
    params = {"a": 1}
    with caplog.at_level(logging.WARNING, logger="growbridge.codes"):
        result = checked("alert", "nope", params)
    assert result == params
    assert "unregistered message code alert.nope" in caplog.text


def test_checked_logs_params_other_than_the_declared_ones(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setitem(CODES["alert"], "probe", Code(params=("a", "b")))
    with caplog.at_level(logging.WARNING, logger="growbridge.codes"):
        more = checked("alert", "probe", {"a": 1, "b": 2, "c": 3})
        fewer = checked("alert", "probe", {"a": 1})
    assert more == {"a": 1, "b": 2, "c": 3}
    assert fewer == {"a": 1}
    assert caplog.text.count("message alert.probe params") == 2


def test_checked_accepts_the_declared_params_in_any_order(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setitem(CODES["alert"], "probe", Code(params=("a", "b")))
    with caplog.at_level(logging.WARNING, logger="growbridge.codes"):
        result = checked("alert", "probe", {"b": 2, "a": 1})
    assert result == {"b": 2, "a": 1}
    assert caplog.text == ""


def test_codes_at_calls_finds_literal_codes(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(
        "x.raise_alert(1, code='a')\nx.raise_alert(2)\nother(code='b')\nraise_alert(code=name)\n",
        encoding="utf-8",
    )
    found = codes_at_calls(tmp_path, {"raise_alert"})
    assert found == [(str(tmp_path / "m.py"), 1, "a")]


def test_observer_and_watchdog_alerts_name_registered_codes() -> None:
    names = {"raise_alert", "_alert", "alert", "_raise", "_enter", "_set"}
    src = REPO / "src" / "growbridge"
    found = codes_at_calls(src / "observer", names)
    found += [
        hit for hit in codes_at_calls(src / "executor", names) if hit[0].endswith("watchdog.py")
    ]
    seen = {code for _, _, code in found}
    assert seen == {
        "data_gap",
        "threshold",
        "frozen_watch",
        "stage_checks",
        "frozen_reading",
        "task_missed",
        "measurement_missing",
        "measurement_outside_window",
        "pump_unexpected_off",
        "pump_unexpected_interlocked",
        "pump_unexpected_failed",
        "pump_unreadable",
        "pump_watchdog_step",
        "pump_watchdog_record",
    }
    assert seen <= set(CODES["alert"])


def test_every_alert_in_the_server_names_a_registered_code() -> None:
    names = {"raise_alert", "_alert", "alert", "_raise", "_enter", "_set"}
    src = REPO / "src" / "growbridge"
    for _, _, code in codes_at_calls(src, names):
        assert code in CODES["alert"], code
    missing = []
    for path in sorted(src.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if called in {"raise_alert", "_alert", "alert"} and not any(
                item.arg == "code" for item in node.keywords
            ):
                missing.append(f"{path.relative_to(src)}:{node.lineno}")
    assert missing == [], f"alerts raised without a code=: {missing}"


def test_the_alert_codes_the_runtime_picks_by_outcome_are_registered() -> None:
    # runtime_agents builds these two families from the outcome; a literal scan cannot see them
    for family in ("agent_task", "audit_task"):
        assert {f"{family}_failed", f"{family}_attention"} <= set(CODES["alert"])
    assert len(CODES["alert"]) == 33
