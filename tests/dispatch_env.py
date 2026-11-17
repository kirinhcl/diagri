"""The dispatch tests' environment, shared by the dispatch and agent test packages."""

import inspect

import pytest
from dispatch_helpers import make_task

from growbridge.agents.budget import CallBudget
from growbridge.agents.dispatch import Dispatcher
from growbridge.agents.handlers import Deps, build_role_tools
from growbridge.agents.handlers_common import bind_task
from growbridge.agents.tools import ROLE_TOOLS, build_toolset
from growbridge.archive.models import Budget, Channel, RuleAction, RunSheet, TimedAction
from growbridge.archive.store import Archive
from growbridge.config import RoleModel
from growbridge.planning.validate import validate_run_sheet
from growbridge.ports import Actor, Denied
from growbridge.sim.fixtures import make_protocol, make_run_sheet
from growbridge.workflow.service import WorkflowService
from growbridge.workflow.tasks import TaskBoard

HIGH_LIGHT = (
    TimedAction(id="light-on", channel=Channel.LIGHT, at="06:00", level=70),
    TimedAction(id="light-off", channel=Channel.LIGHT, at="22:00", level=0),
    TimedAction(id="exhaust-base", channel=Channel.EXHAUST, at="00:00", level=30),
)


class Env:
    """Real workflow, archive, task board and budget over one database and a fake control."""

    def __init__(self, db, clock, control, work_root, archive_root):
        self.db, self.clock, self.control = db, clock, control
        self.work_root = work_root
        self.workflow = WorkflowService(
            db,
            clock,
            control,
            validate=lambda sheet: validate_run_sheet(
                sheet, control.capabilities(), control.safety()
            ),
            # fixture sheets run light 60; the planner tools still run the treatment check
            check_treatments=False,
        )
        self.archive = Archive(db, archive_root, clock)
        self.tasks = TaskBoard(db, clock)
        self.budget = CallBudget(db, clock)
        self.operator = Actor(kind="operator", id="op-1", reauth_at=clock.now())
        self.project_id = self.workflow.create_project("light series", self.operator)
        self.protocol = make_protocol(project_id=self.project_id)
        self.workflow.save_protocol(self.protocol, self.operator)
        self.round_id = self.workflow.create_round(self.project_id, self.protocol.id, self.operator)
        self.budget.set(self.project_id, Budget(max_calls=20, max_cost=50.0))
        self.deps = self.make_deps()
        self.roles = {name: RoleModel() for name in ROLE_TOOLS}

    def make_deps(self, **overrides) -> Deps:
        values = {
            "workflow": self.workflow,
            "control": self.control,
            "archive": self.archive,
            "tasks": self.tasks,
            "clock": self.clock,
            "work_root": self.work_root,
            **overrides,
        }
        return Deps(**values)

    def tools(self, deps: Deps | None = None):
        return build_role_tools(deps or self.deps)

    def dispatcher(self, client, deps: Deps | None = None, budget=None) -> Dispatcher:
        return Dispatcher(
            client,
            self.roles,
            self.tools(deps),
            self.tasks,
            budget or self.budget,
            self.clock,
            self.db,
        )

    async def invoke(self, role: str, name: str, deps: Deps | None = None, /, **fields):
        """Call one tool of a role as a dispatched run of ``task_id`` would (own task by default).

        The run is bound to the task named in the input, which models an honest model; tests of
        a dishonest one use ``invoke_as``. Without a ``task_id`` the role's own task is bound.
        """
        given = fields.get("task_id")
        bound = given if isinstance(given, str) else self.task(role, f"ev-auto-{role}").id
        return await self.invoke_as(bound, role, name, deps, **fields)

    async def invoke_as(
        self, bound: str, role: str, name: str, deps: Deps | None = None, /, **fields
    ):
        """Call a tool while the dispatcher has bound the run to ``bound``."""
        toolset = build_toolset(role, self.tools(deps)[role])
        with bind_task(bound):
            return await toolset.call(name, fields)

    async def refusal(
        self, role: str, name: str, deps: Deps | None = None, /, bound: str | None = None, **fields
    ) -> Denied:
        """The ``Denied`` a tool raises (the toolset text hides its reason, params)."""
        tool = next(t for t in self.tools(deps)[role] if t.name == name)
        given = fields.get("task_id")
        task_id = bound or (given if isinstance(given, str) else self.task(role, "ev-refusal").id)
        bound_field = {"task_id": task_id} if "task_id" in tool.input_model.model_fields else {}
        args = tool.input_model.model_validate({**bound_field, **fields})
        with bind_task(task_id), pytest.raises(Denied) as caught:
            result = tool.handler(args)
            if inspect.isawaitable(result):
                await result
        return caught.value

    async def invoke_unbound(self, role: str, name: str, deps: Deps | None = None, /, **fields):
        """Call a tool outside any dispatched run."""
        toolset = build_toolset(role, self.tools(deps)[role])
        return await toolset.call(name, fields)

    def delegated(self, project_id: str | None = None):
        """The tasks of a project except the ones ``invoke`` created to bind a run."""
        tasks = self.tasks.list(project_id or self.project_id)
        return tuple(t for t in tasks if not t.id.startswith("task-ev-auto-"))

    def task_in(self, project_id: str, owner: str, event: str, **fields):
        """A task of another project (the main project's tasks come from ``task``)."""
        return self.tasks.create(make_task(owner, event, project_id=project_id, **fields))

    def task(self, owner: str, event: str = "ev-1", **fields):
        return self.tasks.create(make_task(owner, event, project_id=self.project_id, **fields))

    def sheet(self, stage_id: str = "stage-1", version: int = 1, **fields) -> RunSheet:
        defaults = {
            "id": f"sheet-{stage_id}",
            "project_id": self.project_id,
            "experiment_id": f"experiment-{stage_id}",
            "stage_id": stage_id,
            "protocol_id": self.protocol.id,
            "version": version,
            "end_actions": (RuleAction(channel=Channel.LIGHT, level=0),),
            "timed_actions": HIGH_LIGHT,  # protocol round 1 is allocated "high" (light 70)
        }
        return make_run_sheet(**{**defaults, **fields})

    def stage_for(self, experiment_id: str) -> str:
        """Register a stage of this project for an experiment, so its snapshots have an owner.

        The stage goes into a second round, leaving the main round's state alone.
        """
        if not hasattr(self, "_experiment_round"):
            self._experiment_round = self.workflow.create_round(
                self.project_id, self.protocol.id, self.operator
            )
        stage_id = f"stage-of-{experiment_id}"
        sheet = self.sheet(stage_id, experiment_id=experiment_id)
        self.workflow.submit_run_sheet(self._experiment_round, sheet, self.operator)
        return stage_id

    def other_project(self) -> tuple[str, str]:
        """A second project with its own protocol, round and one stage of experiment ``exp-b``."""
        project_id = self.workflow.create_project("other", self.operator)
        protocol = make_protocol(project_id=project_id, id="protocol-b")
        self.workflow.save_protocol(protocol, self.operator)
        round_id = self.workflow.create_round(project_id, protocol.id, self.operator)
        sheet = self.sheet(
            "stage-b", project_id=project_id, protocol_id=protocol.id, experiment_id="exp-b"
        )
        self.workflow.submit_run_sheet(round_id, sheet, self.operator)
        return project_id, round_id

    def sheet_json(self, **fields) -> dict:
        return self.sheet(**fields).model_dump(mode="json")
