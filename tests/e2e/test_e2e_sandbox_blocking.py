"""A sandbox analysis runs in a thread: the executor tick must keep going while it runs.

Safety never waits for a model. ``serve`` runs the 1 Hz tick and the model roles in one event
loop, so a blocking ``sandbox.run`` in a tool handler would stop protection rules and the pump
interlock for up to ten minutes.
"""

import asyncio
import threading

from e2e_support import OPERATOR, local

from growbridge.agents.llm import ToolCall
from growbridge.archive import snapshot as snapshots
from growbridge.archive.models import Budget, ResearchTask
from growbridge.research.sandbox import SandboxResult
from growbridge.sim.fixtures import make_protocol, make_safety
from growbridge.sim.llm import ScriptedClient, text_reply, tool_reply

TICKS_REQUIRED = 3
STUCK_SECONDS = 2.0  # a loop-blocking sandbox gives up after this long, so the test cannot hang
TEST_SECONDS = 20.0


class BlockingSandbox:
    """Blocks inside ``run`` until released, and records when it finished."""

    def __init__(self):
        self.release = threading.Event()
        self.done = threading.Event()

    def run(self, script, snapshot_dir, out_dir, timeout):
        released = self.release.wait(STUCK_SECONDS)
        self.done.set()
        return SandboxResult(exit_code=0, stdout="ok", stderr="", timed_out=not released)


async def _round_with_snapshot(world, runtime) -> tuple[str, str]:
    flow, operator = runtime.workflow, world.operator
    runtime.control.approve_safety(make_safety(), OPERATOR)
    project = flow.create_project("lettuce light series", operator)
    protocol = make_protocol(project_id=project)
    flow.save_protocol(protocol, operator)
    round_id = flow.create_round(project, protocol.id, operator)
    runtime.budget.set(project, Budget(max_calls=50, max_cost=100.0))
    sheet = world.sheet(project, protocol_id=protocol.id, protocol_version=protocol.version)
    flow.submit_run_sheet(round_id, sheet, operator)  # gives the experiment its owning project
    start = local("10:00")
    shot = snapshots.freeze(
        runtime.archive, sheet.experiment_id, world.clock, start, start + 10, 1, 120
    )
    return project, shot.id


def _researcher_task(project: str) -> ResearchTask:
    return ResearchTask(
        id="task-ev-block",
        project_id=project,
        question="explore the canopy data",
        owner_role="researcher",
        budget=Budget(max_calls=10, max_cost=5.0),
        trigger_event_id="ev-block",
        correlation_id="corr-1",
    )


async def test_executor_ticks_keep_running_while_a_local_analysis_is_in_the_sandbox(world):
    runtime = await world.boot()
    project, snapshot_id = await _round_with_snapshot(world, runtime)
    sandbox = BlockingSandbox()
    runtime.sandbox = sandbox
    runtime.tasks.create(_researcher_task(project))
    request = ToolCall(
        id="c1",
        name="run_local_analysis",
        input={"task_id": "task-ev-block", "snapshot_id": snapshot_id, "script": "print(1)"},
    )
    client = ScriptedClient([tool_reply(request), text_reply("done")])
    ticks_during_analysis = 0

    async def tick_while_the_analysis_runs() -> None:
        nonlocal ticks_during_analysis
        while not sandbox.done.is_set():
            await runtime.tick()
            if not sandbox.done.is_set():
                ticks_during_analysis += 1
            if ticks_during_analysis >= TICKS_REQUIRED:
                sandbox.release.set()
            await asyncio.sleep(0.01)

    async def both() -> int:
        agents = asyncio.create_task(runtime.run_agents(client))
        await tick_while_the_analysis_runs()
        return await agents

    try:
        finished = await asyncio.wait_for(both(), TEST_SECONDS)
    finally:
        sandbox.release.set()

    assert ticks_during_analysis >= TICKS_REQUIRED, "the event loop was blocked by the sandbox"
    assert finished == 1
    result = client.requests[-1]["messages"][-1]["content"][0]
    assert not result.get("is_error") and '"exit_code": 0' in result["content"]
