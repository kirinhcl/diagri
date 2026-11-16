"""The model loop audits a running stage once per passed stage day (no network, no key)."""

from e2e_support import STAGE

from growbridge.agents.llm import ToolCall
from growbridge.archive.models import Budget, ManualMeasurement
from growbridge.planning.window import MEASUREMENT_GRACE_SECONDS, data_window
from growbridge.runtime_agents import AUDIT_DAY_SECONDS
from growbridge.sim.llm import ScriptedClient, text_reply, tool_reply
from growbridge.workflow.states import StageState, TaskState


def call(name: str, call_id: str = "c1", **fields) -> ToolCall:
    return ToolCall(id=call_id, name=name, input=fields)


class StepClient(ScriptedClient):
    """A scripted client whose replies may be built when they are due, from the board."""

    async def create(self, **request):
        if self._replies and callable(self._replies[0]):
            self._replies[0] = self._replies[0]()
        return await super().create(**request)


async def test_the_loop_audits_a_stage_day_and_raises_a_finding(world):
    runtime = await world.boot()
    project, _round = await world.approved_stage(runtime)
    runtime.budget.set(project, Budget(max_calls=50, max_cost=100.0))
    world.clock.advance(AUDIT_DAY_SECONDS + 60)
    assert runtime.tasks.open_tasks(("auditor",)) == ()  # nothing is made outside the loop

    def finding():
        (task,) = runtime.tasks.open_tasks(("auditor",))
        return tool_reply(
            call(
                "raise_audit_finding",
                task_id=task.id,
                stage_id=STAGE,
                severity="warning",
                summary="light schedule drifted from the run sheet",
                evidence=["day 1 light log"],
            )
        )

    client = StepClient([finding, text_reply("Day 1: one warning raised.")])

    assert await runtime.run_agents(client) == 1

    (task,) = runtime.tasks.list(project)
    assert task.trigger_event_id == f"audit:{STAGE}:day1"
    assert task.state is not TaskState.IN_PROGRESS
    assert [a.kind for a in runtime.book.open()].count("audit_finding") == 1
    assert runtime.workflow.stage(STAGE).state is StageState.RUNNING
    assert task.state is TaskState.DONE
    said = [(e.role, e.kind, e.text) for e in runtime.conversation.entries(project)]
    assert [entry for entry in said if entry[1] == "reply"] == [
        ("auditor", "reply", "Day 1: one warning raised.")
    ]
    assert {role for role, _kind, _text in said} == {"auditor"}  # it woke no other role
    assert await runtime.run_agents(ScriptedClient([])) == 0  # the same day is not audited twice
    assert len(runtime.tasks.list(project)) == 1


async def test_the_tick_runs_the_stage_checks_without_a_model(world):
    runtime = await world.boot()
    await world.approved_stage(runtime)
    _, end = data_window(runtime.workflow.stage(STAGE))
    runtime.archive.add_measurement(
        ManualMeasurement(
            id="m-late",
            experiment_id=f"experiment-{STAGE}",
            batch="b1",
            plant_id="p1",
            layout_version="L1",
            measured_at=end + MEASUREMENT_GRACE_SECONDS + 60,
            position="top",
            method="ruler",
            metric="height",
            value=3.0,
            unit="cm",
            operator="op",
        )
    )

    await world.beat(runtime, 30)

    keys = [(a.kind, a.key, a.severity) for a in runtime.book.open()]
    assert ("measurement_outside_window", f"{STAGE}:m-late", "warning") in keys
    assert runtime.workflow.stage(STAGE).state is StageState.RUNNING
