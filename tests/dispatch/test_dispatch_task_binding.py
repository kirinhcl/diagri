"""The running task is bound by the dispatcher; the model's task_id can never widen access."""

import asyncio

import pytest
from dispatch_helpers import call, script_calls

from growbridge.agents.handlers_common import bound_task_id
from growbridge.archive import snapshot as snapshots
from growbridge.archive.models import SampleRecord
from growbridge.research.sandbox import SandboxResult
from growbridge.sim.clock import START
from growbridge.sim.llm import ScriptedClient
from growbridge.workflow.states import StageState
from growbridge.workflow.store import StageRow


class RecordingSandbox:
    def __init__(self):
        self.calls = []

    def run(self, script, snapshot_dir, out_dir, timeout):
        self.calls.append(snapshot_dir)
        return SandboxResult(exit_code=0, stdout="ok", stderr="", timed_out=False)


class FakeCompute:
    def __init__(self):
        self.submitted = []

    async def submit_compute_job(self, *args):
        self.submitted.append(args)


def _freeze(env, experiment_id: str) -> str:
    for second in range(11):
        env.archive.append_sample(
            SampleRecord(
                id=f"s-{experiment_id}-{second}",
                experiment_id=experiment_id,
                stage_id="stage-1",
                device_id="SIMULATED",
                captured_at=START + second,
                received_at=START + second,
                clock_synced=True,
                data={"temp": 21.0},
            )
        )
    return snapshots.freeze(env.archive, experiment_id, env.clock, START, START + 10, 1, 120).id


class World:
    """Project A (the caller's) and project B, each with a researcher task."""

    def __init__(self, env):
        self.env = env
        self.task_a = env.task("researcher", "ev-a")
        self.project_b, self.round_b = env.other_project()
        self.task_b = env.task_in(self.project_b, "researcher", "ev-b")
        self.snap_b = _freeze(env, "exp-b")
        self.sandbox = RecordingSandbox()
        self.compute = FakeCompute()
        self.deps = env.make_deps(sandbox=self.sandbox, compute=self.compute)

    def calls(self, task_id: str) -> dict[str, dict]:
        """One call per researcher tool that takes a task id, aimed at project B's data."""
        return {
            "run_local_analysis": {
                "task_id": task_id,
                "snapshot_id": self.snap_b,
                "script": "print(1)",
            },
            "freeze_dataset": {"task_id": task_id, "stage_id": "stage-b"},
            "publish_research_report": {
                "task_id": task_id,
                "protocol_id": "protocol-b",
                "treatment_id": "high",
                "snapshots": [{"snapshot_id": self.snap_b, "round": 1}],
            },
            "submit_compute_job": {
                "task_id": task_id,
                "template_id": "t",
                "params": [],
                "inputs": [],
            },
        }

    def untouched(self) -> bool:
        """Nothing was mounted, submitted, frozen or published for project B."""
        return (
            self.sandbox.calls == []
            and self.compute.submitted == []
            and len(self.env.archive.snapshots("exp-b")) == 1
            and self.env.archive.artifacts(self.task_b.id) == ()
        )


@pytest.fixture
def world(env):
    return World(env)


# --- finding 1: the task id comes from the server ---------------------------------------------

TOOLS = ["run_local_analysis", "freeze_dataset", "publish_research_report", "submit_compute_job"]


@pytest.mark.parametrize("name", TOOLS)
async def test_task_a_cannot_use_task_bs_id_in_a_researcher_tool(world, name):
    fields = world.calls(world.task_b.id)[name]

    outcome = await world.env.invoke_as(world.task_a.id, "researcher", name, world.deps, **fields)

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert world.untouched()


@pytest.mark.parametrize("name", TOOLS)
async def test_a_researcher_cannot_use_another_task_of_its_own_project_either(world, name):
    other = world.env.task("researcher", "ev-a2")
    fields = world.calls(other.id)[name]

    outcome = await world.env.invoke_as(world.task_a.id, "researcher", name, world.deps, **fields)

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert world.untouched()


@pytest.mark.parametrize("name", TOOLS)
async def test_a_task_id_call_outside_a_dispatched_run_is_refused(world, name):
    fields = world.calls(world.task_a.id)[name]

    outcome = await world.env.invoke_unbound("researcher", name, world.deps, **fields)

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert world.untouched()


async def test_the_dispatcher_binds_its_task_and_releases_it(world):
    env = world.env
    request = call("run_local_analysis", **world.calls(world.task_b.id)["run_local_analysis"])
    client = ScriptedClient(script_calls(request))

    run = await env.dispatcher(client, world.deps).run_task(world.task_a.id)

    assert run is not None and run.tool_calls[0].is_error
    assert world.sandbox.calls == [] and bound_task_id() is None


async def test_concurrent_runs_each_see_only_their_own_task(env):
    first, second = env.task("orchestrator", "ev-1"), env.task("orchestrator", "ev-2")

    def client_for(task_id: str) -> ScriptedClient:
        return ScriptedClient(script_calls(call("get_task_status", task_id=task_id)))

    runs = await asyncio.gather(
        env.dispatcher(client_for(first.id)).run_task(first.id),
        env.dispatcher(client_for(second.id)).run_task(second.id),
    )

    assert all(run is not None and not run.tool_calls[0].is_error for run in runs)


async def test_a_run_is_unbound_again_after_a_model_failure(env):
    task = env.task("orchestrator")

    class Failing:
        async def create(self, **_):
            raise ConnectionError("down")

    await env.dispatcher(Failing()).run_task(task.id)

    assert bound_task_id() is None


# --- the other roles --------------------------------------------------------------------------


async def test_orchestrator_status_covers_the_bound_task_and_its_descendants_only(world):
    env = world.env
    parent = env.task("orchestrator", "ev-p")
    child = env.task("planner", "ev-c", parent_task_id=parent.id)
    grandchild = env.task("researcher", "ev-g", parent_task_id=child.id)
    stranger = env.task("planner", "ev-s")

    async def status(task_id: str):
        return await env.invoke_as(parent.id, "orchestrator", "get_task_status", task_id=task_id)

    assert not (await status(parent.id)).is_error
    assert not (await status(child.id)).is_error
    assert not (await status(grandchild.id)).is_error
    for foreign in (stranger.id, world.task_b.id):
        outcome = await status(foreign)
        assert outcome.is_error and "denied (scope)" in outcome.content


async def test_orchestrator_cannot_create_or_delegate_into_another_project(world):
    env = world.env
    caller = env.task("orchestrator", "ev-o")
    delegated = await env.invoke_as(
        caller.id,
        "orchestrator",
        "delegate_task",
        project_id=world.project_b,
        to_role="planner",
        goal="g",
        budget={"max_calls": 5, "max_cost": 1.0},
        trigger_event_id="ev-new",
        correlation_id="c",
    )
    created = await env.invoke_as(
        caller.id,
        "orchestrator",
        "create_research_task",
        project_id=world.project_b,
        owner_role="planner",
        question="q",
        trigger_event_id="ev-new2",
        correlation_id="c",
    )

    assert delegated.is_error and "denied (scope)" in delegated.content
    assert created.is_error and "denied (scope)" in created.content
    assert env.tasks.list(world.project_b) == (world.task_b,)


async def test_a_delegation_parent_must_be_the_bound_task(env):
    caller, other = env.task("orchestrator", "ev-o"), env.task("orchestrator", "ev-o2")

    outcome = await env.invoke_as(
        caller.id,
        "orchestrator",
        "delegate_task",
        project_id=env.project_id,
        to_role="planner",
        goal="g",
        budget={"max_calls": 5, "max_cost": 1.0},
        trigger_event_id="ev-new",
        correlation_id="c",
        parent_task_id=other.id,
    )

    assert outcome.is_error and "denied (scope)" in outcome.content


@pytest.mark.parametrize(
    ("role", "name"), [("orchestrator", "submit_run_for_review"), ("planner", "save_plan_draft")]
)
async def test_a_draft_cannot_be_filed_into_another_projects_round(world, role, name):
    env = world.env
    caller = env.task(role, f"ev-{role}")
    sheet = env.sheet(
        "stage-b2", project_id=world.project_b, protocol_id="protocol-b", experiment_id="exp-b2"
    ).model_dump(mode="json")

    outcome = await env.invoke_as(caller.id, role, name, round_id=world.round_b, run_sheet=sheet)

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert env.workflow.store.find_stage("stage-b2") is None


@pytest.mark.parametrize(
    ("role", "name", "fields"),
    [
        ("orchestrator", "get_project_state", {"project_id": "PB"}),
        ("orchestrator", "get_run_status", {"stage_id": "stage-b"}),
        ("planner", "check_experimental_design", {"project_id": "PB", "protocol_id": "protocol-b"}),
        ("planner", "find_prior_runs", {"experiment_id": "exp-b"}),
    ],
)
async def test_reads_of_another_projects_records_are_refused(world, role, name, fields):
    env = world.env
    caller = env.task(role, f"ev-{role}")
    fields = {k: (world.project_b if v == "PB" else v) for k, v in fields.items()}

    outcome = await env.invoke_as(caller.id, role, name, **fields)

    assert outcome.is_error and "denied (scope)" in outcome.content


@pytest.mark.parametrize(
    ("role", "name", "fields"),
    [
        ("orchestrator", "get_task_status", {"task_id": "T"}),
        ("orchestrator", "get_project_state", {"project_id": "P"}),
        ("orchestrator", "get_run_status", {"stage_id": "stage-1"}),
        ("planner", "find_prior_runs", {"experiment_id": "experiment-stage-1"}),
    ],
)
async def test_id_taking_tools_of_every_role_refuse_an_unbound_call(env, role, name, fields):
    task = env.task(role)
    swap = {"T": task.id, "P": env.project_id}
    fields = {k: swap.get(v, v) for k, v in fields.items()}

    outcome = await env.invoke_unbound(role, name, **fields)

    assert outcome.is_error and "denied (scope)" in outcome.content


# --- finding 2: an experiment belongs to one project -----------------------------------------


async def test_an_experiment_claimed_by_two_projects_is_refused(world):
    env = world.env
    env.stage_for("exp-a")
    snapshot_a = _freeze(env, "exp-a")
    env.workflow.store.add_stage(
        StageRow(
            stage_id="stage-dup",
            round_id=world.round_b,
            project_id=world.project_b,
            experiment_id="exp-a",
            device_id="SIMULATED",
            run_sheet_id="sheet-dup",
            run_sheet_version=1,
            state=StageState.PENDING_REVIEW,
            state_at=0.0,
            recovery_number=1,
        )
    )

    outcome = await env.invoke_as(
        world.task_a.id,
        "researcher",
        "run_local_analysis",
        world.deps,
        task_id=world.task_a.id,
        snapshot_id=snapshot_a,
        script="print(1)",
    )

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert world.sandbox.calls == []


async def test_a_run_sheet_reusing_another_projects_experiment_id_is_refused(world):
    env = world.env
    sheet = env.sheet("stage-x", experiment_id="exp-b")  # project A's sheet, B's experiment id

    outcome = await env.invoke_as(
        env.task("planner", "ev-p").id,
        "planner",
        "save_plan_draft",
        round_id=env.round_id,
        run_sheet=sheet.model_dump(mode="json"),
    )

    assert outcome.is_error and "denied (scope)" in outcome.content
    assert env.workflow.store.find_stage("stage-x") is None


async def test_an_experiment_id_may_be_reused_inside_one_project(env):
    env.workflow.submit_run_sheet(env.round_id, env.sheet("stage-1"), env.operator)
    again = env.sheet("stage-2", experiment_id="experiment-stage-1")

    env.workflow.submit_run_sheet(env.round_id, again, env.operator)

    assert env.workflow.store.find_stage("stage-2") is not None
