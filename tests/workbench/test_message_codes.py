"""The server's message code registry (growbridge.codes) and its export for the console
(tests/web/fixtures/message-codes.json). Later tasks check their emission sites with
codes_at_calls."""

import ast
import json
import logging
import re
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
    "denial",
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
    assert len(CODES["alert"]) == 34


def literal_text(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def finding_message_codes(root: Path) -> set[str]:
    """The message code of each _block/_hint call (and of _seed_finding, which picks its variant
    from its second argument) under ``root``; a computed code or variant fails the scan."""
    found: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None)
            if name in {"_block", "_hint"}:
                code = literal_text(node.args[0])
                variant = next((k.value for k in node.keywords if k.arg == "variant"), None)
                if name == "_hint" and code == "seed_mismatch" and variant is not None:
                    continue  # _seed_finding passes its own variant on; counted at its callers
                assert code is not None, f"{path}:{node.lineno}: computed finding code"
                text = "" if variant is None else literal_text(variant)
                assert text is not None, f"{path}:{node.lineno}: computed finding variant"
                found.add(f"{code}.{text}" if text else code)
            elif name == "_seed_finding":
                found.add(f"seed_mismatch.{literal_text(node.args[1])}")
    return found


def test_every_finding_names_a_registered_message_code() -> None:
    emitted = finding_message_codes(REPO / "src" / "growbridge" / "planning")
    assert emitted <= set(CODES["finding"]), emitted - set(CODES["finding"])
    # and the registry lists nothing the server never sends
    assert set(CODES["finding"]) <= emitted, set(CODES["finding"]) - emitted
    assert len(CODES["finding"]) == 43


RECEIPT_CALLS = {"Outcome", "_void_queued"}
COMPUTED_TASK_END = {"pump_off_interlock", "pump_off_watchdog"}  # f"pump_off_{trigger}"


def emitted_codes(root: Path) -> tuple[set[str], set[str]]:
    """(receipt codes, task_end codes) written as literals under ``root``: the ``error_code=`` of
    an Outcome, the ``code=`` of _void_queued, a "error_code" dict key, and for early ends the
    ``code=`` of _end_cycle and the "ended_early_code" dict key. A conditional yields both arms."""
    receipt: set[str] = set()
    task_end: set[str] = set()

    def strings(node: ast.expr) -> set[str]:
        if isinstance(node, ast.JoinedStr):
            return set()  # computed: COMPUTED_TASK_END
        return {
            n.value
            for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        }

    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", getattr(node.func, "attr", None))
                for item in node.keywords:
                    if item.arg == "error_code" and name in RECEIPT_CALLS:
                        receipt |= strings(item.value)
                    elif item.arg == "code" and name == "_void_queued":
                        receipt |= strings(item.value)
                    elif item.arg == "code" and name == "_end_cycle":
                        task_end |= strings(item.value)
            elif isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=True):
                    if isinstance(key, ast.Constant) and key.value == "error_code":
                        receipt |= strings(value)
                    elif isinstance(key, ast.Constant) and key.value == "ended_early_code":
                        task_end |= strings(value)
    return receipt, task_end


def test_every_receipt_and_task_end_code_is_registered() -> None:
    src = REPO / "src" / "growbridge"
    receipt, task_end = emitted_codes(src / "control")
    manual_receipt, manual_end = emitted_codes(src / "workbench")
    receipt, task_end = receipt | manual_receipt, task_end | manual_end | COMPUTED_TASK_END
    assert receipt <= set(CODES["receipt"]), receipt - set(CODES["receipt"])
    assert task_end <= set(CODES["task_end"]), task_end - set(CODES["task_end"])
    # and the registry lists nothing the server never sends
    assert set(CODES["receipt"]) <= receipt, set(CODES["receipt"]) - receipt
    assert set(CODES["task_end"]) <= task_end, set(CODES["task_end"]) - task_end
    assert len(CODES["receipt"]) == 17 and len(CODES["task_end"]) == 7


def compute_codes(root: Path) -> tuple[set[str], set[str]]:
    """(compute_error codes, compute_stuck codes) written as literals under ``root``: the first
    argument of ``coded(...)``, the code (second argument) of ``Problem(...)``, and the second
    element of what ``_why_stuck`` returns."""
    errors: set[str] = set()
    stuck: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", getattr(node.func, "attr", None))
                at = {"coded": 0, "Problem": 1}.get(name or "")
                if at is not None and len(node.args) > at:
                    arg = node.args[at]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        errors.add(arg.value)
            elif isinstance(node, ast.FunctionDef) and node.name == "_why_stuck":
                for ret in ast.walk(node):
                    if isinstance(ret, ast.Return) and isinstance(ret.value, ast.Tuple):
                        code = ret.value.elts[1]
                        assert isinstance(code, ast.Constant), "a stuck code must be a literal"
                        stuck.add(code.value)
    return errors, stuck


def test_every_compute_error_and_stuck_code_is_registered() -> None:
    errors, stuck = compute_codes(REPO / "src" / "growbridge" / "compute")
    assert errors == set(CODES["compute_error"]), errors ^ set(CODES["compute_error"])
    assert stuck == set(CODES["compute_stuck"]), stuck ^ set(CODES["compute_stuck"])
    assert {code for code, spec in CODES["compute_error"].items() if not spec.action} == {
        "late_cancelled",
        "cancelled_no_job",
        "settled_by_operator",
    }


def test_chat_end_codes_in_dispatch_match_the_registry() -> None:
    src = REPO / "src" / "growbridge" / "agents"
    found = codes_at_calls(src, {"_end", "RunEnd"})  # RunEnd is where the codes now live
    assert {code for _, _, code in found} == set(CODES["chat_end"])
    assert set(CODES["chat_end"]) == {
        "denied",
        "model_unavailable",
        "model_stopped",
        "undelivered",
        "run_finished",
    }


def test_estimate_codes_in_stats_match_the_registry() -> None:
    source = (REPO / "src" / "growbridge" / "research" / "stats.py").read_text(encoding="utf-8")
    emitted = set(re.findall(r'note_code="(\w+)"', source))

    assert emitted == set(CODES["estimate"]), emitted ^ set(CODES["estimate"])
    assert CODES["estimate"]["too_few_blocks"].params == ("blocks", "min_blocks")
    assert CODES["estimate"]["sampled_p"] == Code(("flips", "blocks"), action=False)
