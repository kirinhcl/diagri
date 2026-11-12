import pytest
from dispatch_helpers import make_task

from growbridge.agents.budget import CallBudget
from growbridge.agents.dispatch import Dispatcher
from growbridge.agents.handlers import Deps, build_role_tools
from growbridge.agents.tools import ROLE_TOOLS, build_toolset
from growbridge.archive.db import Database
from growbridge.archive.models import Budget, Channel, RuleAction, RunSheet
from growbridge.archive.store import Archive
from growbridge.config import RoleModel
from growbridge.planning.validate import validate_run_sheet
from growbridge.ports import Actor
from growbridge.sim.clock import FakeClock
from growbridge.sim.control import FakeControl
from growbridge.sim.fixtures import make_protocol, make_run_sheet
from growbridge.workflow.service import WorkflowService
from growbridge.workflow.tasks import TaskBoard


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
        """Call one tool of a role directly, as the loop would; returns the ToolOutcome."""
        toolset = build_toolset(role, self.tools(deps)[role])
        return await toolset.call(name, fields)

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


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "dispatch.db")
    yield database
    database.close()


@pytest.fixture
def env(db, clock, tmp_path):
    return Env(db, clock, FakeControl(clock), tmp_path / "work", tmp_path / "archive")
