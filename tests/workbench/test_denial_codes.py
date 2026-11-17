"""A refusal carries a registered ``reason`` and ``params`` (growbridge.denial_codes).

``refusal_sites`` is the AST scan that keeps every ``Denied(...)`` and ``rejected(...)`` honest:
outside ``PENDING`` each one names a registered reason of its own coarse code."""

import ast
import json
from pathlib import Path
from typing import NamedTuple

import pytest

import growbridge
from growbridge.codes import Code
from growbridge.denial_codes import DENIAL_CODES
from growbridge.ports import Denied
from growbridge.workbench.api import refusal
from growbridge.workbench.common import rejected

SRC = Path(growbridge.__file__).resolve().parent
assert SRC.is_relative_to(Path(__file__).resolve().parents[2] / "src"), "run with PYTHONPATH=src"
REFUSAL_CALLS = {"Denied", "rejected"}


class Site(NamedTuple):
    path: str  # relative to src/growbridge
    line: int
    code: str | None
    reason: str | None


def _literal(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def refusal_sites(root: Path) -> list[Site]:
    """Each ``Denied(...)`` and ``rejected(...)`` call under ``root``: its coarse code (the first
    argument; ``"param"`` for ``rejected``) and its literal ``reason=`` keyword, if any."""
    found: list[Site] = []
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if called not in REFUSAL_CALLS:
                continue
            code = (
                "param" if called == "rejected" else (_literal(node.args[0]) if node.args else None)
            )
            reason = next((_literal(k.value) for k in node.keywords if k.arg == "reason"), None)
            found.append(Site(path.relative_to(root).as_posix(), node.lineno, code, reason))
    return found


def sent_elsewhere() -> set[str]:
    return set()


# Files that still have a refusal without a reason; each task removes the files it converts.
PENDING: set[str] = {
    "agents/budget.py",
    "agents/dispatch.py",
    "agents/handlers_auditor.py",
    "agents/handlers_common.py",
    "agents/handlers_evidence.py",
    "agents/handlers_orchestrator.py",
    "agents/handlers_planner.py",
    "agents/handlers_report.py",
    "agents/handlers_researcher.py",
    "agents/tools.py",
    "archive/snapshot.py",
    "compute/service.py",
    "research/analysis.py",
    "research/holdout.py",
    "research/preregistration.py",
    "research/sandbox.py",
    "runtime_compute.py",
    "workbench/analysis.py",
    "workbench/api.py",
    "workbench/auth.py",
    "workbench/manual_tasks.py",
}


def test_a_denial_keeps_code_and_message_and_carries_reason_and_params() -> None:
    error = Denied(
        "state",
        "stage s1 is paused; it cannot pause",
        reason="stage_not_pausable",
        params={"stage_id": "s1", "state": "paused"},
    )
    assert error.code == "state" and str(error) == "stage s1 is paused; it cannot pause"
    assert error.reason == "stage_not_pausable"
    assert error.params == {"stage_id": "s1", "state": "paused"}


def test_an_old_style_denial_has_no_reason_and_empty_params() -> None:
    error = Denied("state", "x")
    assert error.reason is None and error.params == {}


def test_a_reason_under_another_code_is_logged_and_still_raised(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setitem(DENIAL_CODES, "demo_reason", Code(("stage_id",), of="state"))
    error = Denied("scope", "m", reason="demo_reason", params={"stage_id": "s"})
    assert error.reason == "demo_reason"
    assert "demo_reason" in caplog.text and "scope" in caplog.text


def test_the_refusal_body_adds_reason_and_params_and_keeps_the_status() -> None:
    response = refusal(
        Denied(
            "state",
            "m",
            reason="stage_not_pausable",
            params={"stage_id": "s1", "state": "paused"},
        )
    )
    assert response.status_code == 409
    assert json.loads(bytes(response.body))["detail"] == {
        "code": "state",
        "reason": "stage_not_pausable",
        "params": {"stage_id": "s1", "state": "paused"},
        "message": "m",
    }


def test_an_old_style_refusal_body_has_a_null_reason_and_empty_params() -> None:
    detail = json.loads(bytes(refusal(Denied("budget", "m")).body))["detail"]
    assert detail == {"code": "budget", "reason": None, "params": {}, "message": "m"}


def test_rejected_carries_the_param_code_a_reason_and_params() -> None:
    error = rejected("too long", reason="id_length", params={"max_length": 64})
    assert error.status_code == 422
    assert error.detail == {
        "code": "param",
        "reason": "id_length",
        "params": {"max_length": 64},
        "message": "too long",
    }


def test_the_denial_family_is_the_registry_dict() -> None:
    from growbridge.codes import CODES

    assert CODES["denial"] is DENIAL_CODES


def test_every_refusal_outside_pending_names_a_registered_reason_of_its_code() -> None:
    for site in refusal_sites(SRC):
        if site.path in PENDING:
            continue
        assert site.reason in DENIAL_CODES, site
        assert DENIAL_CODES[site.reason].of == site.code, site


def test_pending_lists_only_files_that_still_have_a_refusal_without_reason() -> None:
    open_files = {s.path for s in refusal_sites(SRC) if s.reason is None}
    assert PENDING == open_files


def test_every_registered_reason_is_sent_somewhere() -> None:
    sent = {s.reason for s in refusal_sites(SRC)} | sent_elsewhere()
    assert set(DENIAL_CODES) <= sent
