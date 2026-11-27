from __future__ import annotations

import json

import pytest
from agent_helpers import EchoInput, make_tool
from pydantic import BaseModel, Field

from growbridge.agents.tools import CONTROL_TOOLS, ROLE_TOOLS, Tool, build_toolset
from growbridge.ports import Denied


def test_role_tools_cover_exactly_the_four_model_roles():
    assert set(ROLE_TOOLS) == {"orchestrator", "planner", "researcher", "auditor"}


def test_no_role_can_ever_hold_a_control_tool():
    for names in ROLE_TOOLS.values():
        assert not (names & CONTROL_TOOLS)
    assert {"start_approved_stage", "run_pump", "stop_stage"} <= CONTROL_TOOLS


def test_role_sets_match_spec():
    assert "freeze_dataset" in ROLE_TOOLS["researcher"]
    assert "submit_run_for_review" not in ROLE_TOOLS["orchestrator"]
    assert "validate_run_sheet" in ROLE_TOOLS["planner"]


@pytest.mark.parametrize("name", ["start_approved_stage", "run_pump"])
def test_requesting_control_tool_is_denied(name):
    registry = [make_tool("get_project_state"), make_tool(name)]
    with pytest.raises(Denied) as exc:
        build_toolset("orchestrator", registry, allowed=[name])
    assert exc.value.code == "model_role"


def test_requesting_tool_of_another_role_is_denied():
    with pytest.raises(Denied) as exc:
        build_toolset("orchestrator", [make_tool("freeze_dataset")], allowed=["freeze_dataset"])
    assert exc.value.code == "model_role"


def test_unknown_role_is_denied():
    with pytest.raises(Denied) as exc:
        build_toolset("executor", [make_tool("get_project_state")])
    assert exc.value.code == "model_role"


def test_control_tool_in_registry_never_reaches_the_toolset():
    registry = [make_tool("get_project_state"), make_tool("run_pump")]
    toolset = build_toolset("orchestrator", registry)
    assert [s["name"] for s in toolset.schemas()] == ["get_project_state"]


def test_empty_allowed_means_every_role_tool_in_registry():
    registry = [make_tool("get_project_state"), make_tool("get_task_status")]
    assert len(build_toolset("orchestrator", registry).schemas()) == 2


def test_allowed_narrows_the_set():
    registry = [make_tool("get_project_state"), make_tool("get_task_status")]
    toolset = build_toolset("orchestrator", registry, allowed=["get_task_status"])
    assert [s["name"] for s in toolset.schemas()] == ["get_task_status"]


def test_schema_is_closed_and_not_strict():
    schema = build_toolset("orchestrator", [make_tool("get_project_state")]).schemas()[0]
    assert "strict" not in schema
    assert schema["input_schema"]["additionalProperties"] is False
    assert schema["input_schema"]["properties"]["text"]["type"] == "string"


def test_nested_objects_are_closed_too():
    class Inner(BaseModel):
        a: int

    class Outer(BaseModel):
        inner: Inner

    async def h(_):
        return {}

    tool = Tool(name="get_run_status", description="d", input_model=Outer, handler=h)
    schema = build_toolset("orchestrator", [tool]).schemas()[0]["input_schema"]
    assert schema["properties"]["inner"]["additionalProperties"] is False


def test_schemas_are_self_contained():
    """A server that renders ``$ref`` as an untyped value must still show the nested fields."""

    class Inner(BaseModel):
        a: int

    class Outer(BaseModel):
        first: Inner
        second: list[Inner] = Field(default_factory=list, description="more of them")

    async def h(_):
        return {}

    tool = Tool(name="get_run_status", description="d", input_model=Outer, handler=h)
    schema = build_toolset("orchestrator", [tool]).schemas()[0]["input_schema"]
    assert "$ref" not in json.dumps(schema) and "$defs" not in schema
    assert schema["properties"]["first"]["required"] == ["a"]
    assert schema["properties"]["second"]["items"]["properties"]["a"]["type"] == "integer"
    assert schema["properties"]["second"]["description"] == "more of them"


def test_every_model_role_tool_schema_is_self_contained(tmp_path):
    from growbridge.agents.handlers import Deps, build_role_tools

    deps = Deps(*(None,) * 5, work_root=tmp_path)  # schemas only: no handler is called
    for role, tools in build_role_tools(deps).items():
        for schema in build_toolset(role, tools).schemas():
            assert "$ref" not in json.dumps(schema["input_schema"]), schema["name"]


# Tools are sent without ``strict``. Its grammar rejected DiAGRI's schemas three ways on
# 2026-11-27 (claude-opus-5-5): numeric and length limits, more than 24 optional parameters in one
# request (the planner has 57), and "the compiled grammar is too large", a limit no test here can
# see. Every input is validated against its input model when the tool is called instead.
class Bounded(BaseModel):
    limit: int = Field(1, ge=1, le=10)
    ratio: float = Field(0.5, gt=0, lt=1)
    note: str = Field("x", min_length=1, max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=8)


def _bounded_toolset():
    async def h(_):
        return {"ok": True}

    tool = Tool(name="get_run_status", description="d", input_model=Bounded, handler=h)
    return build_toolset("orchestrator", [tool])


def test_limits_stay_in_the_schema_the_model_sees():
    props = _bounded_toolset().schemas()[0]["input_schema"]["properties"]
    assert (props["limit"]["minimum"], props["limit"]["maximum"]) == (1, 10)
    assert (props["ratio"]["exclusiveMinimum"], props["ratio"]["exclusiveMaximum"]) == (0, 1)
    assert (props["note"]["minLength"], props["note"]["maxLength"]) == (1, 50)
    assert props["tags"]["maxItems"] == 8


async def test_limits_are_enforced_when_the_tool_runs():
    toolset = _bounded_toolset()
    assert not (await toolset.call("get_run_status", {"limit": 10})).is_error
    for bad in ({"limit": 11}, {"ratio": 1}, {"note": ""}, {"tags": ["t"] * 9}):
        assert (await toolset.call("get_run_status", bad)).is_error, bad


@pytest.mark.parametrize("restricted", [False, True])
def test_no_model_role_tool_is_sent_strict(tmp_path, restricted):
    from growbridge.agents.handlers import Deps, build_role_tools

    deps = Deps(*(None,) * 5, work_root=tmp_path)  # schemas only: no handler is called
    for role, tools in build_role_tools(deps).items():
        for schema in build_toolset(role, tools).schemas(restricted=restricted):
            assert set(schema) == {"name", "description", "input_schema"}, (role, schema["name"])


def test_restricted_schemas_drop_sandbox_and_write_tools():
    registry = [
        make_tool("get_project_state"),
        make_tool("create_research_task", writes=True),
        make_tool("get_task_status", sandbox=True),
    ]
    toolset = build_toolset("orchestrator", registry)
    assert len(toolset.schemas()) == 3
    assert [s["name"] for s in toolset.schemas(restricted=True)] == ["get_project_state"]


async def test_call_valid_input_returns_serialised_result():
    toolset = build_toolset("orchestrator", [make_tool("get_project_state")])
    out = await toolset.call("get_project_state", {"text": "ab", "count": 2})
    assert not out.is_error
    assert "abab" in out.content


async def test_call_invalid_input_returns_error_not_exception():
    toolset = build_toolset("orchestrator", [make_tool("get_project_state")])
    out = await toolset.call("get_project_state", {"text": 5, "bogus": 1})
    assert out.is_error
    assert out.content.startswith("Error:")


async def test_call_unknown_tool_is_error():
    toolset = build_toolset("orchestrator", [make_tool("get_project_state")])
    out = await toolset.call("run_pump", {"seconds": 5})
    assert out.is_error and out.content.startswith("Error:")


async def test_call_restricted_refuses_write_tool():
    toolset = build_toolset("orchestrator", [make_tool("create_research_task", writes=True)])
    out = await toolset.call("create_research_task", {"text": "x"}, restricted=True)
    assert out.is_error


async def test_handler_denied_and_crash_become_error_results():
    async def denied(_):
        raise Denied("scope", "nope")

    async def crash(_):
        raise RuntimeError("boom at /Users/someone/data/app.db")

    reg = [
        Tool(name="get_project_state", description="d", input_model=EchoInput, handler=denied),
        Tool(name="get_run_status", description="d", input_model=EchoInput, handler=crash),
    ]
    toolset = build_toolset("orchestrator", reg)
    first = await toolset.call("get_project_state", {"text": "x"})
    second = await toolset.call("get_run_status", {"text": "x"})
    assert first.is_error and "scope" in first.content
    assert second.is_error and "RuntimeError" in second.content
    assert "boom" not in second.content and "/Users" not in second.content


async def test_sync_handler_supported():
    def handler(args: EchoInput):
        return "plain"

    tool = Tool(name="get_project_state", description="d", input_model=EchoInput, handler=handler)
    out = await build_toolset("orchestrator", [tool]).call("get_project_state", {"text": "x"})
    assert out.content == "plain" and not out.is_error


def test_reads_web_flag_is_exposed():
    toolset = build_toolset("planner", [make_tool("search_and_verify_sources", reads_web=True)])
    assert toolset.reads_web("search_and_verify_sources") is True
    assert toolset.reads_web("nonexistent") is False


def test_the_local_analysis_tool_says_how_the_script_finds_the_snapshot(tmp_path):
    """The script gets ``<snapshot_dir> <out_dir>`` as arguments and runs in the empty output
    directory; a model that is not told so reads nothing (seen in a Claude research round)."""
    from growbridge.agents.handlers import Deps, build_role_tools
    from growbridge.archive.snapshot import MANIFEST

    deps = Deps(*(None,) * 5, work_root=tmp_path)  # descriptions only: no handler is called
    (tool,) = [t for t in build_role_tools(deps)["researcher"] if t.name == "run_local_analysis"]

    for needed in ("sys.argv[1]", "sys.argv[2]", MANIFEST, "samples.jsonl", "measurements.jsonl"):
        assert needed in tool.description, needed
