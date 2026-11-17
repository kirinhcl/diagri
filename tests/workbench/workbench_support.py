"""Helpers for the workbench tests: real workflow, archive and operator services over a
recording fake control, served through FastAPI's TestClient on a LAN and an overlay address."""

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from vocab_support import TEST_CATALOG

from growbridge.agents.budget import CallBudget
from growbridge.agents.conversation import ConversationLog
from growbridge.api import create_app
from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.archive.models import (
    ActionRecord,
    ActionState,
    CareRule,
    Channel,
    RightKind,
    RuleAction,
    TimedAction,
)
from growbridge.archive.store import Archive
from growbridge.config import Settings
from growbridge.observer.alerts import AlertBook
from growbridge.ports import ActionRequest, Actor
from growbridge.research.analysis import ConfirmatoryRunner
from growbridge.research.holdout import HoldoutRegistry, project_outcomes
from growbridge.research.sandbox import SandboxResult
from growbridge.sim.clock import FakeClock
from growbridge.sim.control import FakeControl
from growbridge.sim.fixtures import make_protocol, make_run_sheet
from growbridge.workbench.api import create_workbench
from growbridge.workbench.auth import Operators
from growbridge.workflow.service import WorkflowService
from growbridge.workflow.tasks import TaskBoard

LAN_HOST = "lan.test"
OVERLAY_HOST = "overlay.test"
MAIN_PORT = 8766  # the loopback listener the overlay proxy forwards to
LAN_PORT = 9443  # the on-site listener
SECRET = "correct horse battery staple"  # obviously fake
ROLE_TOKENS = {
    "planner": "fake-planner-token-0000000000000000",
    "analyst": "fake-analyst-token-0000000000000000",
}
FAST_SCRYPT = 2**10  # keep the tests quick; production uses the module default


class RecordingControl(FakeControl):
    """FakeControl that records the writes it is asked for and keeps their receipts."""

    def __init__(self, clock: Clock):
        super().__init__(clock)
        self.submitted: list[ActionRequest] = []
        self.irrigated: list[tuple[ActionRequest, float]] = []
        self.receipts: dict[str, ActionRecord] = {}
        self.irrigation_update: dict = {}  # how the next pump run settles (e.g. cut short)

    def _record(self, request: ActionRequest) -> ActionRecord:
        record = ActionRecord(
            request_id=request.request_id,
            state=ActionState.CONFIRMED,
            channel=request.channel,
            planned_level=request.level,
            right_number=request.right_number,
            right_kind=RightKind.MANUAL,
            trigger=request.trigger,
            created_at=self.clock.now(),
            operator=request.operator,
            experiment_id=request.experiment_id,
            stage_id=request.stage_id,
        )
        self.receipts[request.request_id] = record
        return record

    async def submit(self, request: ActionRequest) -> ActionRecord:
        self.submitted.append(request)
        return self._record(request)

    async def irrigate(
        self, request: ActionRequest, seconds: float, planned: bool = False
    ) -> ActionRecord:
        self.irrigated.append((request, seconds) if not planned else (request, seconds, "planned"))
        settled = {"ran_seconds": seconds, **self.irrigation_update}
        record = self._record(request).model_copy(update=settled)
        self.receipts[request.request_id] = record
        return record

    def receipt(self, request_id: str) -> ActionRecord | None:
        return self.receipts.get(request_id)


class ScriptedSandbox:
    """Stands in for the code sandbox: records every run and answers with ``result``."""

    def __init__(self):
        self.result = SandboxResult(0, "analysis finished", "", False)
        self.runs: list[tuple[bytes, Path, Path]] = []

    def run(self, script, snapshot_dir, out_dir, timeout):
        self.runs.append((script.read_bytes(), snapshot_dir, out_dir))
        return self.result


class Bench:
    """One database, one clock, the services and an app with the workbench mounted."""

    def __init__(
        self,
        tmp_path,
        lan_port: int | None = LAN_PORT,
        compute_factory=None,
        check_treatments: bool = False,
    ):
        self.clock = FakeClock()
        self.db = Database(tmp_path / "workbench.db")
        self.control = RecordingControl(self.clock)
        # fixture sheets run light 60, not the fixture protocol's 40/70 treatments
        self.workflow = WorkflowService(
            self.db,
            self.clock,
            self.control,
            check_treatments=check_treatments,
            catalog=TEST_CATALOG,
        )
        self.archive = Archive(self.db, tmp_path / "archive", self.clock)
        self.alerts = AlertBook(self.db, self.clock)
        self.tasks = TaskBoard(self.db, self.clock)
        self.budget = CallBudget(self.db, self.clock)
        self.operators = Operators(self.db, self.clock, scrypt_n=FAST_SCRYPT)
        self.sandbox = ScriptedSandbox()
        self.runner = ConfirmatoryRunner(self.db, self.clock, self.sandbox, tmp_path / "analysis")
        outcomes = project_outcomes(
            self.archive.batch_metrics, self.workflow.store.projects_of_experiment, TEST_CATALOG
        )
        self.holdout = HoldoutRegistry(self.db, self.clock, outcomes, TEST_CATALOG)
        self.conversation = ConversationLog(self.db, self.clock)
        # a callable taking this bench: the compute service shares its database and clock
        self.compute = None if compute_factory is None else compute_factory(self)
        self.settings = Settings(
            device="SIMULATED",
            token="s" * 32,
            data_dir=tmp_path,
            port=MAIN_PORT,
            lan_port=lan_port,
            auto_research=True,
            lan_hosts=[LAN_HOST],
            overlay_hosts=[OVERLAY_HOST],
        )
        self.router = create_workbench(
            self.workflow,
            self.control,
            self.archive,
            self.operators,
            self.settings,
            ROLE_TOKENS,
            alerts=self.alerts,
            tasks=self.tasks,
            budget=self.budget,
            runner=self.runner,
            holdout=self.holdout,
            compute=self.compute,
            conversation=self.conversation,
        )
        self.app = create_app(self.settings, bridge=object(), workbench=self.router)
        self.lan = TestClient(self.app, base_url=f"http://{LAN_HOST}:{LAN_PORT}")
        self.overlay = TestClient(self.app, base_url=f"https://{OVERLAY_HOST}:{MAIN_PORT}")
        self.project_id = ""
        self.round_id = ""

    # --- http helpers --------------------------------------------------------------------------

    @staticmethod
    def ui(client: TestClient) -> dict[str, str]:
        """The headers a same-origin page sends on a state-changing request."""
        return {"Origin": str(client.base_url).rstrip("/"), "x-growbridge-ui": "1"}

    def post(self, client: TestClient, path: str, body: dict | None = None, **kwargs):
        headers = {**self.ui(client), **kwargs.pop("headers", {})}
        return client.post(path, json=body or {}, headers=headers, **kwargs)

    def approve(self, client: TestClient, stage_id: str = "stage-1", digest: str | None = None):
        """Approve a stage the way the console does: for the digest of the sheet it reads first."""
        if digest is None:
            digest = client.get(f"/wb/stages/{stage_id}/run-sheet").json()["run_sheet_digest"]
        return self.post(client, f"/wb/stages/{stage_id}/approve", {"expected_digest": digest})

    def login(self, client: TestClient, name: str = "alice", secret: str = SECRET):
        return self.post(client, "/wb/login", {"name": name, "secret": secret})

    @staticmethod
    def model(role: str = "planner") -> dict[str, str]:
        return {"Authorization": f"Bearer {ROLE_TOKENS[role]}"}

    # --- stage helpers -------------------------------------------------------------------------

    @property
    def designer(self) -> Actor:
        return Actor(kind="workflow", id="designer")

    def seed_round(self) -> str:
        self.project_id = self.workflow.create_project("lettuce light series", self.designer)
        protocol = make_protocol(
            project_id=self.project_id,
            stages=("vegetative",),
            variables=("canopy_area_growth", "height", "yield_g"),
        )
        self.workflow.save_protocol(protocol, self.designer)
        self.round_id = self.workflow.create_round(self.project_id, protocol.id, self.designer)
        return self.round_id

    def sheet(self, stage_id: str = "stage-1", version: int = 1):
        steps = (
            TimedAction(id="care-on", channel=Channel.LIGHT, at="06:00", level=60),
            TimedAction(id="care-off", channel=Channel.LIGHT, at="22:00", level=0),
        )
        return make_run_sheet(
            id=f"sheet-{stage_id}",
            project_id=self.project_id,
            experiment_id=f"experiment-{stage_id}",
            stage_id=stage_id,
            version=version,
            care_rules=(CareRule(id="care-light", channel=Channel.LIGHT, schedule=steps),),
            end_actions=(RuleAction(channel=Channel.LIGHT, level=0),),
        )

    def pending(self, stage_id: str = "stage-1") -> str:
        if not self.round_id:
            self.seed_round()
        self.workflow.submit_run_sheet(self.round_id, self.sheet(stage_id), self.designer)
        return stage_id

    def state(self, stage_id: str = "stage-1") -> str:
        return self.workflow.stage(stage_id).state.value

    @staticmethod
    def run(coroutine):
        return asyncio.run(coroutine)
