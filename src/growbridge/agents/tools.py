"""Role-scoped tool registry for the model roles (architecture doc §4, §5.2, §11.6).

Handlers are injected by the runtime; this module only owns the role -> tool-name mapping, schema
generation and input validation. Model roles can never obtain a stage or device control tool.
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from growbridge.archive.models import Model
from growbridge.ports import Denied

log = logging.getLogger(__name__)

# Long enough for a validation report of a whole run sheet: a clipped one makes the model fix
# a field or two per turn.
MAX_ERROR_CHARS = 4000

ROLE_TOOLS: dict[str, frozenset[str]] = {
    "orchestrator": frozenset(
        {
            "read_round_history",
            "get_project_state",
            "get_run_status",
            "create_research_task",
            "delegate_task",
            "get_task_status",
            "read_artifact",
        }
    ),
    "planner": frozenset(
        {
            "read_round_history",
            "get_device_capabilities",
            "find_prior_runs",
            "lookup_crop_conditions",
            "search_and_verify_sources",
            "check_experimental_design",
            "estimate_sample_size",
            "validate_run_sheet",
            "save_plan_draft",
            "query_evidence",
            "propose_evidence_card",
        }
    ),
    "researcher": frozenset(
        {
            "read_round_history",
            "inspect_stage_data",
            "freeze_dataset",
            "query_evidence",
            "run_local_analysis",
            "submit_compute_job",
            "get_compute_job",
            "fetch_compute_artifacts",
            "publish_research_report",
        }
    ),
    "auditor": frozenset(
        {
            "read_round_history",
            "get_project_state",
            "get_run_status",
            "inspect_stage_data",
            "get_stage_records",
            "raise_audit_finding",
        }
    ),
}

# Stage and device control: never reachable from a model role, whatever the configuration says.
CONTROL_TOOLS: frozenset[str] = frozenset(
    {
        "start_approved_stage",
        "pause_stage",
        "resume_stage",
        "stop_stage",
        "get_stage_status",
        "get_action_receipt",
        "record_manual_measurement",
        "approve_run_sheet",
        "approve_stage",
        "set_light",
        "set_exhaust",
        "set_fan",
        "set_outlet",
        "run_pump",
    }
)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable[[Any], Any]  # receives the validated input model; sync or async
    reads_web: bool = False
    writes: bool = False
    sandbox: bool = False


class ToolOutcome(Model):
    name: str
    content: str
    is_error: bool = False


def _close_objects(node: Any) -> Any:
    """Return a copy of a JSON schema with ``additionalProperties: false`` on every object."""
    if isinstance(node, dict):
        out = {key: _close_objects(value) for key, value in node.items()}
        if out.get("type") == "object" or "properties" in out:
            out["additionalProperties"] = False
        return out
    if isinstance(node, list):
        return [_close_objects(item) for item in node]
    return node


def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    """Return a copy of a JSON schema with every local ``$ref`` replaced by its definition.

    Some model servers render a ``$ref`` parameter as an untyped value, so the model never sees
    the nested fields (seen with Ollama: a run sheet arrived as ``any``). The tool input models
    have no recursive definitions, so the result is finite; a sibling of ``$ref`` (a description,
    say) is kept on top of the definition.
    """
    if isinstance(node, dict):
        if "$ref" in node:
            name = node["$ref"].removeprefix("#/$defs/")
            siblings = {k: _inline_refs(v, defs) for k, v in node.items() if k != "$ref"}
            return {**_inline_refs(defs[name], defs), **siblings}
        return {k: _inline_refs(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_inline_refs(item, defs) for item in node]
    return node


def input_schema(model: type[BaseModel]) -> dict:
    """The self-contained, closed JSON schema a model sees for a tool input."""
    schema = model.model_json_schema()
    return _close_objects(_inline_refs(schema, schema.get("$defs", {})))


def _serialise(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, BaseModel):
        return result.model_dump_json()
    return json.dumps(result, default=str, ensure_ascii=False)


def _error(name: str, message: str) -> ToolOutcome:
    return ToolOutcome(name=name, content=f"Error: {message}"[:MAX_ERROR_CHARS], is_error=True)


class Toolset:
    def __init__(self, role: str, tools: Sequence[Tool]):
        self.role = role
        self._tools = {tool.name: tool for tool in tools}

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def _visible(self, restricted: bool) -> list[Tool]:
        return [t for t in self._tools.values() if not (restricted and (t.sandbox or t.writes))]

    def schemas(self, restricted: bool = False) -> list[dict]:
        """Strict tool definitions; ``restricted`` hides sandbox and write tools."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "strict": True,
                "input_schema": input_schema(tool.input_model),
            }
            for tool in self._visible(restricted)
        ]

    def reads_web(self, name: str) -> bool:
        tool = self._tools.get(name)
        return bool(tool and tool.reads_web)

    async def call(self, name: str, raw_input: Any, restricted: bool = False) -> ToolOutcome:
        """Validate and run one tool; every failure is returned as an error result."""
        tool = self._tools.get(name)
        if tool is None or tool not in self._visible(restricted):
            return _error(name, f"tool {name!r} is not available")
        try:
            args = tool.input_model.model_validate(raw_input)
        except ValidationError as exc:
            return _error(name, f"invalid input for {name}: {exc.error_count()} problem(s): {exc}")
        return await self._run(tool, args)

    async def _run(self, tool: Tool, args: BaseModel) -> ToolOutcome:
        try:
            result = tool.handler(args)
            if inspect.isawaitable(result):
                result = await result
        except Denied as exc:
            return _error(tool.name, f"denied ({exc.code}): {exc}")
        except Exception as exc:
            log.exception("tool %s failed", tool.name)
            return _error(tool.name, f"{tool.name} failed ({type(exc).__name__})")
        return ToolOutcome(name=tool.name, content=_serialise(result))


def build_toolset(role: str, tools: Sequence[Tool], allowed: Sequence[str] = ()) -> Toolset:
    """Select the tools a role may use.

    ``allowed`` (the configured tool list; empty means all the role may use) can only narrow the
    role's set. Asking for a control tool or one of another role is ``Denied("model_role")``.
    """
    role_set = ROLE_TOOLS.get(role)
    if role_set is None:
        raise Denied("model_role", f"{role!r} is not a model role")
    for name in allowed:
        if name in CONTROL_TOOLS or name not in role_set:
            raise Denied("model_role", f"role {role!r} may not use tool {name!r}")
    wanted = set(allowed) if allowed else role_set
    return Toolset(role, [t for t in tools if t.name in wanted and t.name not in CONTROL_TOOLS])
