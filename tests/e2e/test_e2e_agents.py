"""Model roles on the simulator: scripted client, no network, no key (architecture doc §4, §5)."""

from e2e_support import OPERATOR, STAGE

from growbridge.agents.llm import ToolCall
from growbridge.archive.models import Budget, ManualMeasurement, ResearchTask
from growbridge.cli import model_client_or_none
from growbridge.sim.fixtures import make_protocol, make_safety
from growbridge.sim.llm import ScriptedClient, text_reply, tool_reply
from growbridge.workflow.states import RoundState, StageState, TaskState

EXPERIMENT = f"experiment-{STAGE}"


def call(name: str, call_id: str = "c1", **fields) -> ToolCall:
    return ToolCall(id=call_id, name=name, input=fields)


class StepClient(ScriptedClient):
    """A scripted client whose replies may be built from what has happened so far."""

    async def create(self, **request):
        if self._replies and callable(self._replies[0]):
            self._replies[0] = self._replies[0]()
        return await super().create(**request)


class RaisingClient:
    def __init__(self):
        self.calls = 0

    async def create(self, **_request):
        self.calls += 1
        raise ConnectionError("model endpoint unreachable")


def task(project_id: str, owner: str, event: str, **fields) -> ResearchTask:
    values = {
        "id": f"task-{event}",
        "project_id": project_id,
        "question": "does more light speed up canopy growth?",
        "owner_role": owner,
        "budget": Budget(max_calls=10, max_cost=5.0),
        "trigger_event_id": event,
        "correlation_id": "corr-1",
        **fields,
    }
    return ResearchTask(**values)


async def design(world, runtime):
    """Project, protocol and round made by the operator; the model budget is set."""
    flow, operator = runtime.workflow, world.operator
    runtime.control.approve_safety(make_safety(), OPERATOR)
    project = flow.create_project("lettuce light series", operator)
    protocol = make_protocol(project_id=project)
    flow.save_protocol(protocol, operator)
    round_id = flow.create_round(project, protocol.id, operator)
    runtime.budget.set(project, Budget(max_calls=50, max_cost=100.0))
    return project, protocol, round_id


def sheet_json(world, project, protocol) -> dict:
    return world.model_sheet(project, protocol).model_dump(mode="json")


def tool_blocks(client) -> list[dict]:
    return client.requests[-1]["messages"][-1]["content"]


def device_writes(world) -> list:
    return [c for c in world.sim.commands if c["method"] == "setConfigField"]


def measure(runtime, at: float) -> None:
    """One synthetic canopy measurement of the stage's experiment (round 1, treatment high)."""
    runtime.archive.add_measurement(
        ManualMeasurement(
            id="m-1",
            experiment_id=EXPERIMENT,
            batch="batch-1",
            plant_id="plant-1",
            layout_version="layout-1",
            measured_at=at,
            position="tent-1",
            method="image",
            metric="canopy_area_growth",
            value=1.30,
            unit="cm2/day",
            operator=OPERATOR,
        )
    )


def delegation(project: str, parent: str) -> ToolCall:
    return call(
        "delegate_task",
        project_id=project,
        to_role="planner",
        goal="draft a 60 % light run sheet",
        budget={"max_calls": 8, "max_cost": 2.5},
        trigger_event_id="ev-plan",
        correlation_id="corr-1",
        constraints=["no pump"],
        expected_artifacts=["run_sheet"],
        parent_task_id=parent,
    )


async def test_model_driven_round_from_delegation_to_delivery(world):
    runtime = await world.boot()
    project, protocol, round_id = await design(world, runtime)
    flow, operator = runtime.workflow, world.operator
    runtime.tasks.create(task(project, "orchestrator", "ev-orch"))

    # the orchestrator delegates a planning task with a full handoff
    client = ScriptedClient([tool_reply(delegation(project, "task-ev-orch")), text_reply("ok")])
    assert await runtime.run_agents(client) == 1
    assert runtime.tasks.get("task-ev-orch").state is TaskState.DONE
    (planning,) = [t for t in runtime.tasks.list(project) if t.owner_role == "planner"]
    assert planning.state is TaskState.IN_PROGRESS and planning.parent_task_id == "task-ev-orch"

    # the planner validates and saves a draft: it waits for review and nothing is started
    sheet = sheet_json(world, project, protocol)
    client = ScriptedClient(
        [
            tool_reply(call("validate_run_sheet", run_sheet=sheet)),
            tool_reply(call("save_plan_draft", round_id=round_id, run_sheet=sheet)),
            text_reply("drafted"),
        ]
    )
    assert await runtime.run_agents(client) == 1
    assert runtime.tasks.get(planning.id).state is TaskState.DONE
    assert flow.round_state(round_id) is RoundState.STAGE_REVIEW
    assert flow.stage(STAGE).state is StageState.PENDING_REVIEW
    assert flow.approvals(STAGE) == () and flow.active_stage() is None
    assert device_writes(world) == []

    # the ended planning task wakes the orchestrator with a follow-up naming it
    (follow,) = [
        t for t in runtime.tasks.list(project) if t.trigger_event_id.startswith("followup:")
    ]
    assert follow.owner_role == "orchestrator" and f"task:{planning.id}" in follow.input_refs
    assert await runtime.run_agents(ScriptedClient([text_reply("please review the draft")])) == 1
    assert runtime.tasks.get(follow.id).state is TaskState.DONE

    # the operator approves and starts; ticks run the stage to its end
    flow.approve(STAGE, operator)
    await flow.start_stage(STAGE, operator)
    assert flow.round_state(round_id) is RoundState.STAGE_RUNNING
    await world.run_until_ended(runtime)
    assert flow.round_state(round_id) is RoundState.DATA_VERIFICATION

    # the researcher freezes the dataset and publishes the report; the round is delivered
    measure(runtime, flow.stage(STAGE).started_at + 10)
    runtime.tasks.create(task(project, "researcher", "ev-res"))
    freeze = call("freeze_dataset", task_id="task-ev-res", stage_id=STAGE, round_id=round_id)

    def publish() -> object:
        snapshot = runtime.archive.snapshots(EXPERIMENT)[-1]
        assert flow.round_state(round_id) is RoundState.ANALYSIS
        return tool_reply(
            call(
                "publish_research_report",
                task_id="task-ev-res",
                protocol_id=protocol.id,
                treatment_id="high",
                snapshots=[{"snapshot_id": snapshot.id, "round": 1}],
                evidence_chain=["measurement m-1"],
                limitations=["one round only"],
                next_round="collect the other rounds",
                unresolved=[],
                round_id=round_id,
            )
        )

    client = StepClient([tool_reply(freeze), publish, text_reply("published")])
    assert await runtime.run_agents(client) == 1
    assert runtime.tasks.get("task-ev-res").state is TaskState.DONE
    assert flow.round_state(round_id) is RoundState.DELIVERED
    assert [a.kind for a in runtime.archive.artifacts("task-ev-res")] == ["research_report"]


async def test_stage_runs_to_its_end_while_the_model_fails_on_every_call(world):
    runtime = await world.boot()
    project, _round = await world.approved_stage(runtime)
    runtime.budget.set(project, Budget(max_calls=50, max_cost=100.0))
    runtime.tasks.create(task(project, "planner", "ev-plan"))
    client = RaisingClient()

    assert await runtime.run_agents(client) == 0

    assert client.calls >= 1
    assert runtime.tasks.get("task-ev-plan").state is TaskState.NEEDS_ATTENTION
    assert [a.key for a in runtime.book.open() if a.kind == "agent_task"] == ["task-ev-plan"]
    await world.run_until_ended(runtime)
    assert runtime.workflow.stage(STAGE).state is StageState.ENDED


async def test_a_planner_cannot_approve_or_start_by_tool_or_by_input_field(world):
    runtime = await world.boot()
    project, protocol, round_id = await design(world, runtime)
    sheet = sheet_json(world, project, protocol)
    runtime.workflow.submit_run_sheet(
        round_id,
        world.sheet(project, protocol_id=protocol.id, protocol_version=protocol.version),
        world.operator,
    )
    runtime.tasks.create(task(project, "planner", "ev-plan"))
    attempts = [
        call("start_approved_stage", "c1", stage_id=STAGE),
        call("approve_stage", "c2", stage_id=STAGE),
        call("save_plan_draft", "c3", round_id=round_id, run_sheet=sheet, approved=True),
        call("validate_run_sheet", "c4", run_sheet=sheet, approved_by="op-1"),
    ]
    client = ScriptedClient([tool_reply(*attempts), text_reply("done")])

    await runtime.run_agents(client)

    assert all(block["is_error"] for block in tool_blocks(client))
    assert runtime.workflow.stage(STAGE).state is StageState.PENDING_REVIEW
    assert runtime.workflow.approvals(STAGE) == ()
    assert runtime.workflow.active_stage() is None
    assert device_writes(world) == []


async def test_tick_never_calls_a_model(world):
    runtime = await world.boot()
    project, _round = await world.approved_stage(runtime)
    runtime.budget.set(project, Budget(max_calls=50, max_cost=100.0))
    runtime.tasks.create(task(project, "orchestrator", "ev-orch"))
    client = RaisingClient()
    runtime.dispatcher(client)  # a dispatcher exists, but only run_agents may use it

    for _ in range(5):
        await world.beat(runtime, 30)

    assert client.calls == 0
    assert runtime.tasks.get("task-ev-orch").state is TaskState.IN_PROGRESS


async def test_one_failing_task_does_not_stop_the_others(world, monkeypatch):
    runtime = await world.boot()
    project, _protocol, _round = await design(world, runtime)
    runtime.tasks.create(task(project, "orchestrator", "ev-a"))
    runtime.tasks.create(task(project, "orchestrator", "ev-b"))
    dispatcher = runtime.dispatcher(ScriptedClient([text_reply("ok")]))
    original = dispatcher.run_task
    seen = []

    async def flaky(task_id):
        seen.append(task_id)
        if task_id == "task-ev-a":
            raise RuntimeError("dispatcher bug")
        return await original(task_id)

    monkeypatch.setattr(dispatcher, "run_task", flaky)
    monkeypatch.setattr(runtime, "dispatcher", lambda _client: dispatcher)

    assert await runtime.run_agents(object()) == 1
    assert seen == ["task-ev-a", "task-ev-b"]
    assert [a.key for a in runtime.book.open() if a.kind == "agent_task"] == ["task-ev-a"]


async def test_missing_model_client_raises_an_alert_and_serving_goes_on(world, monkeypatch):
    runtime = await world.boot()

    def unavailable(*_args, **_kwargs):
        raise ImportError("anthropic is not installed")

    monkeypatch.setattr("growbridge.agents.llm.AnthropicClient", unavailable)

    assert model_client_or_none(runtime) is None
    assert [a.kind for a in runtime.book.open() if a.kind == "model_client"] == ["model_client"]
