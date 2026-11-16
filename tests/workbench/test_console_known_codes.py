"""The console's list of server codes (tests/web/fixtures/known-codes.json) names every code the
server can send where the server can enumerate them: a code missing there would reach the
operator as "unknown" instead of as text. tests/web/catalog.test.mjs checks the texts."""

import ast
import json
from collections.abc import Iterable
from pathlib import Path
from typing import get_args

import growbridge
import growbridge.planning.validate as validate_module
import growbridge.workflow.service as service_module
from growbridge.agents.tools import ROLE_TOOLS
from growbridge.archive.models import Channel, Condition, Entry, EvidenceCard, Label, TaskKind
from growbridge.compute.phases import Phase
from growbridge.control.device import SENSORS
from growbridge.observer.alerts import Severity
from growbridge.observer.health import PROBE_NAMES
from growbridge.planning.manual_tasks import Status
from growbridge.ports import Difference, StageEventKind
from growbridge.research.analysis import AnalysisRun, Conclusion, RunStatus
from growbridge.workbench.reads import STAGE_KINDS
from growbridge.workflow.states import RoundState, StageState, TaskState

REPO = Path(__file__).resolve().parents[2]
# The lists are checked against the code this checkout ships, not another install of growbridge
# (a shared virtualenv may import another checkout's older code and pass against it).
assert Path(growbridge.__file__).resolve().is_relative_to(REPO / "src"), (
    f"imported growbridge from {growbridge.__file__}, not {REPO / 'src'}: run with PYTHONPATH=src"
)
KNOWN_CODES = REPO / "tests" / "web" / "fixtures" / "known-codes.json"
WORKFLOW = Path(service_module.__file__).parent
PLANNING = Path(validate_module.__file__).parent


def known() -> dict[str, set[str]]:
    data = json.loads(KNOWN_CODES.read_text(encoding="utf-8"))
    return {prefix: set(codes) for prefix, codes in data.items() if not prefix.startswith("_")}


def calls(files: Iterable[Path]) -> list[ast.Call]:
    trees = [ast.parse(path.read_text(encoding="utf-8")) for path in files]
    return [node for tree in trees for node in ast.walk(tree) if isinstance(node, ast.Call)]


def strings(found: list[ast.Call], name: str, position: int | None, keyword: str = "") -> set[str]:
    """String literals passed to calls of ``name`` at ``position`` or as ``keyword``."""
    values: list[ast.expr] = []
    for node in found:
        func = node.func
        called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if called != name:
            continue
        if position is not None and position < len(node.args):
            values.append(node.args[position])
        values += [item.value for item in node.keywords if keyword and item.arg == keyword]
    return {v.value for v in values if isinstance(v, ast.Constant) and isinstance(v.value, str)}


def literal(annotation) -> set[str]:
    return set(get_args(annotation))


def test_console_lists_every_enumerable_code():
    codes = known()
    assert {k.value for k in StageEventKind} <= codes["history.event"]
    states = {s.value for s in StageState} | {s.value for s in RoundState}
    assert states | {s.value for s in TaskState} <= codes["state"]
    assert literal(Phase) <= codes["state"]
    assert {name for tools in ROLE_TOOLS.values() for name in tools} <= codes["chat.tool"]
    assert set(ROLE_TOOLS) | {"user"} <= codes["chat.role"]


def test_console_lists_every_code_of_a_fixed_type():
    codes = known()
    assert literal(Condition.model_fields["op"].annotation) == codes["safety.op"]
    assert literal(Difference.model_fields["field"].annotation) == codes["diff.field"]
    assert {c.value for c in Channel} <= codes["channel"]
    assert set(SENSORS) <= codes["metric"]
    assert literal(Severity) <= codes["severity"]
    assert literal(Status) <= codes["tasks.status"]
    assert literal(TaskKind) <= codes["tasks.kind"]
    assert {e.value for e in Entry} <= codes["entry"]
    assert literal(EvidenceCard.model_fields["source_class"].annotation) <= codes["evidence.class"]
    assert literal(Label) <= codes["report.labels"]
    assert literal(Conclusion) <= codes["report.conclusions"]
    assert literal(RunStatus) <= codes["analysis.runState"]
    assert literal(AnalysisRun.model_fields["status"].annotation) <= codes["analysis.runState"]
    assert set(STAGE_KINDS.values()) <= codes["inbox.kind"]


def test_console_lists_every_history_event_the_workflow_names():
    found = calls(WORKFLOW.glob("*.py"))
    events = strings(found, "Plan", 1) | strings(found, "add_history", 1)
    events |= strings(found, "_enter_recovery", 0)
    assert {"start", "round_aborted", "restart"} <= events  # the scan sees each way of naming one
    assert events <= known()["history.event"]


def test_console_lists_every_finding_code():
    found = calls(PLANNING.glob("*.py"))
    findings = strings(found, "Finding", None, "code")
    findings |= strings(found, "_block", 0) | strings(found, "_hint", 0)
    assert {"manual_task", "treatment_not_applied", "seed_mismatch"} <= findings
    assert findings <= known()["finding"]


def method(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"no function {name} in runtime.py")


def test_console_lists_every_tick_step_probe_and_heartbeat():
    tree = ast.parse((Path(growbridge.__file__).parent / "runtime.py").read_text(encoding="utf-8"))
    steps = {
        node.elts[0].value
        for node in ast.walk(method(tree, "tick"))
        if isinstance(node, ast.Tuple)
        and len(node.elts) == 2
        and isinstance(node.elts[0], ast.Constant)
        and isinstance(node.elts[0].value, str)
    }
    signals = {
        key.value
        for node in ast.walk(method(tree, "_monitor_alerts"))
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "signals" for target in node.targets)
        and isinstance(node.value, ast.Dict)
        for key in node.value.keys
        if isinstance(key, ast.Constant)
    }
    assert {"archive", "health", "backup"} <= steps and signals == {"host", "run"}
    codes = known()
    assert steps <= codes["tickStep"]
    assert set(PROBE_NAMES) <= codes["probe"]
    assert signals <= codes["heartbeat"]
