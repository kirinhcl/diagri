import json

from dispatch_helpers import call, script_calls

from growbridge.agents.dispatch import follow_up
from growbridge.agents.tools import ROLE_TOOLS
from growbridge.archive.ids import file_digest
from growbridge.archive.models import Artifact
from growbridge.sim.llm import ScriptedClient
from growbridge.workflow.states import StageState, TaskState

HANDOFF = {
    "to_role": "planner",
    "goal": "draft a 70 % light run sheet",
    "constraints": ["no pump", "max 7 days"],
    "evidence_refs": ["card-1"],
    "expected_artifacts": ["run_sheet"],
    "budget": {"max_calls": 8, "max_cost": 2.5},
    "trigger_event_id": "ev-delegate-1",
    "correlation_id": "corr-9",
}


def _payload(outcome) -> dict:
    assert not outcome.is_error, outcome.content
    return json.loads(outcome.content)


def _register(env, artifact_id: str, path, task_id: str | None = None) -> None:
    owner = task_id or env.task("researcher", "ev-art").id  # an artifact belongs to a real task
    env.archive.add_artifact(
        Artifact(
            id=artifact_id,
            task_id=owner,
            kind="note",
            path=str(path),
            sha256=file_digest(path),
            label="descriptive",
        )
    )


async def test_orchestrator_delegates_with_a_full_handoff(env):
    parent = env.task("orchestrator", "ev-parent")
    client = ScriptedClient(
        script_calls(
            call("delegate_task", project_id=env.project_id, parent_task_id=parent.id, **HANDOFF)
        )
    )

    run = await env.dispatcher(client).run_task(parent.id)

    assert run is not None and not run.tool_calls[0].is_error
    child = env.tasks.list(env.project_id)[-1]
    assert child.owner_role == "planner"
    assert child.question == HANDOFF["goal"]
    assert child.constraints == ("no pump", "max 7 days")
    assert child.input_refs == ("card-1",)
    assert child.expected_artifacts == ("run_sheet",)
    assert (child.budget.max_calls, child.budget.max_cost) == (8, 2.5)
    assert child.parent_task_id == parent.id
    assert child.trigger_event_id == "ev-delegate-1"
    assert child.correlation_id == "corr-9"
    assert child.state is TaskState.IN_PROGRESS


async def test_delegating_the_same_trigger_twice_creates_one_task(env):
    fields = {"project_id": env.project_id, **HANDOFF}

    first = _payload(await env.invoke("orchestrator", "delegate_task", **fields))
    second = _payload(await env.invoke("orchestrator", "delegate_task", **fields))

    assert first["task_id"] == second["task_id"]
    assert len(env.delegated()) == 1


async def test_a_trigger_already_used_by_another_task_is_refused(env):
    """A real model copied its own task's trigger id: the tool returned the orchestrator's own task
    as ``reused`` and the model believed it had delegated. Another task's trigger is refused."""
    parent = env.task("orchestrator", "goal:project:dev:goal-1", question="does light help?")
    for name, role_field in (("create_research_task", "owner_role"), ("delegate_task", "to_role")):
        fields = {k: v for k, v in HANDOFF.items() if k not in {"to_role", "goal"}}
        text = {"question" if name == "create_research_task" else "goal": "design it"}
        if name == "create_research_task":
            fields.pop("evidence_refs")
        copied = {role_field: "planner", "trigger_event_id": parent.trigger_event_id}
        body = {**fields, **text, **copied, "project_id": env.project_id}
        outcome = await env.invoke_as(parent.id, "orchestrator", name, **body)
        assert outcome.is_error and "already belongs to task" in outcome.content
        assert parent.id in outcome.content
    assert [t.id for t in env.delegated()] == [parent.id]


async def test_delegation_to_a_non_model_role_is_rejected_by_the_schema(env):
    outcome = await env.invoke(
        "orchestrator",
        "delegate_task",
        project_id=env.project_id,
        **{**HANDOFF, "to_role": "executor"},
    )

    assert outcome.is_error and not env.delegated()


async def test_handoff_without_trigger_or_correlation_ids_is_rejected(env):
    partial = {k: v for k, v in HANDOFF.items() if k != "correlation_id"}

    outcome = await env.invoke(
        "orchestrator", "delegate_task", project_id=env.project_id, **partial
    )

    assert outcome.is_error and not env.delegated()


async def test_a_delegated_task_hangs_under_the_running_task_when_no_parent_is_named(env):
    """The tool promises a follow-up when the task ends; only a child of the orchestrator's
    task gets one."""
    parent = env.task("orchestrator", "ev-parent")
    client = ScriptedClient(
        script_calls(call("delegate_task", project_id=env.project_id, **HANDOFF))
    )

    run = await env.dispatcher(client).run_task(parent.id)

    assert run is not None and not run.tool_calls[0].is_error
    child = env.tasks.list(env.project_id)[-1]
    assert child.owner_role == "planner" and child.parent_task_id == parent.id


async def test_create_research_task_makes_a_top_level_task(env):
    body = _payload(
        await env.invoke(
            "orchestrator",
            "create_research_task",
            project_id=env.project_id,
            owner_role="researcher",
            question="analyse round 1",
            trigger_event_id="ev-new",
            correlation_id="corr-1",
        )
    )

    task = env.tasks.get(body["task_id"])
    assert task.owner_role == "researcher" and task.parent_task_id is None
    assert "follow-up" not in body["next"]  # a top-level task is never reported back


async def test_the_orchestrator_cannot_write_a_run_sheet(env):
    """Run sheets come from the planner, whose checks and design work the orchestrator skips."""
    names = {t.name for t in env.tools()["orchestrator"]}

    assert not names & {"submit_run_for_review", "save_plan_draft", "validate_run_sheet"}
    assert not ROLE_TOOLS["orchestrator"] & {"submit_run_for_review", "save_plan_draft"}


async def test_get_run_status_and_project_state_are_read_only(env):
    env.workflow.submit_run_sheet(env.round_id, env.sheet(), env.operator)
    env.task("planner")

    status = _payload(await env.invoke("orchestrator", "get_run_status", stage_id="stage-1"))
    state = _payload(
        await env.invoke(
            "orchestrator", "get_project_state", project_id=env.project_id, round_id=env.round_id
        )
    )

    assert status["state"] == StageState.PENDING_REVIEW.value
    assert "planner" in {t["owner_role"] for t in state["tasks"]}
    assert state["round_state"] == env.workflow.round_state(env.round_id).value


async def test_get_task_status_lists_artifact_ids(env, tmp_path):
    task = env.task("researcher")
    path = tmp_path / "note.txt"
    path.write_text("hello")
    _register(env, "art-1", path, task.id)

    body = _payload(await env.invoke("orchestrator", "get_task_status", task_id=task.id))

    assert body["state"] == TaskState.IN_PROGRESS.value
    assert body["artifacts"] == [{"id": "art-1", "kind": "note", "label": "descriptive"}]


async def test_read_artifact_returns_verified_text_inside_the_work_root(env):
    env.work_root.mkdir(parents=True)
    path = env.work_root / "note.txt"
    path.write_text("canopy grew")
    _register(env, "art-2", path)

    body = _payload(await env.invoke("orchestrator", "read_artifact", artifact_id="art-2"))

    assert body["text"] == "canopy grew"


async def test_read_artifact_refuses_files_outside_the_known_roots(env, tmp_path):
    outside = tmp_path / "elsewhere" / "secret.txt"
    outside.parent.mkdir()
    outside.write_text("token")
    _register(env, "art-3", outside)

    outcome = await env.invoke("orchestrator", "read_artifact", artifact_id="art-3")

    assert outcome.is_error and "token" not in outcome.content


async def test_read_artifact_refuses_a_file_changed_after_registration(env):
    env.work_root.mkdir(parents=True)
    path = env.work_root / "note.txt"
    path.write_text("original")
    _register(env, "art-4", path)
    path.write_text("tampered")

    outcome = await env.invoke("orchestrator", "read_artifact", artifact_id="art-4")

    assert outcome.is_error and "tampered" not in outcome.content


async def test_delegated_created_and_follow_up_tasks_inherit_the_language(env):
    parent = env.task("orchestrator", "ev-parent", language="en")
    client = ScriptedClient(
        script_calls(call("delegate_task", project_id=env.project_id, **HANDOFF))
    )
    await env.dispatcher(client).run_task(parent.id)
    (child,) = [t for t in env.tasks.list(env.project_id) if t.parent_task_id == parent.id]
    made = _payload(
        await env.invoke_as(
            parent.id,
            "orchestrator",
            "create_research_task",
            project_id=env.project_id,
            owner_role="researcher",
            question="analyse round 1",
            trigger_event_id="ev-new",
            correlation_id="corr-1",
        )
    )

    assert child.language == "en"
    assert env.tasks.get(made["task_id"]).language == "en"
    assert follow_up(child, TaskState.DONE, "fine").language == "en"
    assert follow_up(env.task("planner", "ev-old"), TaskState.DONE, "fine").language is None
