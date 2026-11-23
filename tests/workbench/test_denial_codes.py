"""A refusal carries a registered ``reason`` and ``params`` (growbridge.denial_codes).

``refusal_sites`` is the AST scan that keeps every ``Denied(...)`` and ``rejected(...)`` honest:
each one names a registered reason of its own coarse code."""

import ast
import json
from pathlib import Path
from typing import NamedTuple

import pytest

import growbridge
from growbridge.api import BRIDGE_ERROR_CODES
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
    keys: frozenset[str] | None = None  # the keys of a literal ``params={...}``, if there is one


def _literal(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _dict_keys(node: ast.expr | None) -> frozenset[str] | None:
    """The keys of a dict literal of plain string keys; None for anything else."""
    if not isinstance(node, ast.Dict):
        return None
    keys = [_literal(k) if k is not None else None for k in node.keys]
    return None if None in keys else frozenset(k for k in keys if k)


def literal_keys(call: ast.Call) -> frozenset[str] | None:
    """The keys of the call's ``params={...}`` when it is a dict literal of plain string keys."""
    return next((_dict_keys(k.value) for k in call.keywords if k.arg == "params"), None)


def _translates_a_refusal(call: ast.Call) -> bool:
    """``as_denied``'s ``Denied(..., reason=error.reason, ...)``: it carries a RelationRefused's
    reason, which ``relation_refused_sites`` checks where it is raised."""
    return any(
        k.arg == "reason"
        and isinstance(k.value, ast.Attribute)
        and k.value.attr == "reason"
        and getattr(k.value.value, "id", None) == "error"
        for k in call.keywords
    )


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
            if _translates_a_refusal(node):
                continue
            code = (
                "param" if called == "rejected" else (_literal(node.args[0]) if node.args else None)
            )
            reason = next((_literal(k.value) for k in node.keywords if k.arg == "reason"), None)
            found.append(
                Site(
                    path.relative_to(root).as_posix(), node.lineno, code, reason, literal_keys(node)
                )
            )
    return found


def coded_http_sites(root: Path) -> list[tuple[str, str | None, str | None]]:
    """(file, literal ``code=``, literal ``reason=``) of every ``CodedHTTPError(...)`` call."""
    found: list[tuple[str, str | None, str | None]] = []
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "CodedHTTPError":
                literals = {k.arg: _literal(k.value) for k in node.keywords}
                found.append(
                    (
                        path.relative_to(root).as_posix(),
                        literals.get("code"),
                        literals.get("reason"),
                    )
                )
    return found


def coded_http_reasons(root: Path) -> set[str]:
    """The literal ``reason=`` of every ``CodedHTTPError(...)`` call under ``root``."""
    return {reason for _, _, reason in coded_http_sites(root) if reason}


def relation_refused_sites(root: Path) -> list[Site]:
    """Each ``RelationRefused(reason, message, params)`` call under ``root`` with a literal
    reason. The evidence-relation rules raise it and ``as_denied`` turns it into a ``Denied``
    with the coarse code the registry gives the reason, so the site itself names no code."""
    found: list[Site] = []
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (
                isinstance(node, ast.Call) and getattr(node.func, "id", None) == "RelationRefused"
            ):
                continue
            reason = _literal(node.args[0]) if node.args else None
            if reason:
                params = _dict_keys(node.args[2]) if len(node.args) > 2 else None
                site = Site(path.relative_to(root).as_posix(), node.lineno, None, reason, params)
                found.append(site)
    return found


def relation_refused_reasons(root: Path) -> set[str]:
    """The literal reason of every ``RelationRefused(...)`` call under ``root``."""
    return {site.reason for site in relation_refused_sites(root) if site.reason}


def sent_elsewhere() -> set[str]:
    """Reasons sent by ``CodedHTTPError`` calls, by the root app's ``BridgeError`` table and by
    the evidence-relation rules' ``RelationRefused``."""
    return (
        coded_http_reasons(SRC)
        | {reason for _, reason in BRIDGE_ERROR_CODES.values()}
        | relation_refused_reasons(SRC)
    )


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


def test_every_refusal_names_a_registered_reason_of_its_code() -> None:
    for site in refusal_sites(SRC):
        assert site.reason in DENIAL_CODES, site
        assert DENIAL_CODES[site.reason].of == site.code, site
    for site in relation_refused_sites(SRC):
        assert site.reason in DENIAL_CODES, site


def test_every_registered_reason_is_sent_somewhere() -> None:
    sent = {s.reason for s in refusal_sites(SRC)} | sent_elsewhere()
    assert set(DENIAL_CODES) <= sent


def test_a_literal_params_dict_has_exactly_the_keys_the_registry_lists() -> None:
    for site in [*refusal_sites(SRC), *relation_refused_sites(SRC)]:
        if site.reason in DENIAL_CODES and site.keys is not None:
            assert site.keys == set(DENIAL_CODES[site.reason].params), site


def test_a_coded_http_error_has_the_code_its_reason_refines() -> None:
    sites = coded_http_sites(SRC)
    assert sites, "the root app sends coded errors"
    for path, code, reason in sites:
        assert reason in DENIAL_CODES, (path, reason)
        assert code == DENIAL_CODES[reason].of, (path, code, reason)


def test_registering_a_reason_twice_is_refused_and_leaves_the_first_in_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from growbridge.denial_codes import _register

    monkeypatch.setitem(DENIAL_CODES, "demo_twice", Code(("a",), of="state"))
    with pytest.raises(ValueError, match="demo_twice"):
        _register("scope", ("demo_twice", ("b",)))
    assert DENIAL_CODES["demo_twice"] == Code(("a",), of="state")


def test_rejected_logs_a_reason_under_another_code_or_with_other_params_and_still_answers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    wrong_code = rejected("m", reason="stage_not_pausable", params={"stage_id": "s", "state": "x"})
    wrong_params = rejected("m", reason="id_length", params={"surprise": 1})

    assert wrong_code.status_code == wrong_params.status_code == 422
    assert "stage_not_pausable is registered under state, not param" in caplog.text
    assert "id_length" in caplog.text and "surprise" in caplog.text
