"""HTTP routes of the workbench (architecture §5.2 and §10), mounted under ``/wb``.

Who the caller is comes from the server alone: an operator session cookie, or a per-role model
bearer token. Fields in a request body that claim an identity, a permission or an entry are
ignored. Model roles may read and may submit a draft run sheet, nothing else.
"""

import hmac
from collections.abc import Mapping
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ConfigDict, Field, StrictInt

from growbridge.agents.conversation import ConversationLog
from growbridge.archive.ids import new_id
from growbridge.archive.models import (
    Channel,
    Entry,
    ManualMeasurement,
    RunSheet,
    SafetyConfig,
    check_level,
)
from growbridge.archive.store import Archive
from growbridge.compute.service import ComputeService
from growbridge.config import Settings
from growbridge.observer.alerts import AlertBook
from growbridge.ports import ActionRequest, Actor, ControlPort, Denied, StageRuntime
from growbridge.research.analysis import ConfirmatoryRunner
from growbridge.research.holdout import HoldoutRegistry
from growbridge.vocab import Variable
from growbridge.vocab.checks import check_measurement
from growbridge.workbench.analysis import add_analysis_routes
from growbridge.workbench.auth import (
    SESSION_SECONDS,
    Operators,
    allowed_origins,
    entry_for,
    host_only,
)
from growbridge.workbench.common import REQUEST_ID, Body, rejected
from growbridge.workbench.compute import add_compute_routes
from growbridge.workbench.evidence import add_evidence_routes
from growbridge.workbench.holdouts import add_holdout_routes
from growbridge.workbench.manual_tasks import add_manual_task_routes
from growbridge.workbench.reads import add_read_routes
from growbridge.workbench.rounds import ProjectBudget, add_round_routes
from growbridge.workflow.naming import STAGE_NAME_KEYS, stage_names
from growbridge.workflow.permissions import REAUTH_SECONDS, require_operator
from growbridge.workflow.service import WorkflowService
from growbridge.workflow.states import StageState
from growbridge.workflow.tasks import TaskBoard

COOKIE = "growbridge_operator"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
MAX_IRRIGATION_SECONDS = 60
MIN_ROLE_TOKEN_LENGTH = 32
STATUS_BY_CODE = {"state": 409, "session": 401, "locked": 429}


# --- request bodies ----------------------------------------------------------------------------


class Login(Body):
    name: str = Field(min_length=1, max_length=64)
    secret: str = Field(min_length=1, max_length=256)


class Reauth(Body):
    secret: str = Field(min_length=1, max_length=256)


class Approve(Body):
    """The digest of the run sheet that was reviewed. Required, and no other field is accepted: a
    misnamed field must not silently approve whatever sheet is current."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    expected_digest: str = Field(min_length=1, max_length=128)


class Pause(Body):
    reason: str = Field(default="operator request", max_length=200)


class Handback(Body):
    accept_as_intervention: bool = False


class Note(Body):
    note: str = Field(min_length=1, max_length=500)


class Draft(Body):
    round_id: str = Field(min_length=1, max_length=100)
    run_sheet: RunSheet


class ManualWrite(Body):
    stage_id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(pattern=REQUEST_ID)
    level: StrictInt
    note: str = Field(default="", max_length=200)


class Irrigation(Body):
    stage_id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(pattern=REQUEST_ID)
    seconds: float = Field(gt=0, le=MAX_IRRIGATION_SECONDS)
    note: str = Field(default="", max_length=200)


class MeasurementIn(Body):
    id: str | None = Field(default=None, min_length=1, max_length=100)
    experiment_id: str = Field(min_length=1, max_length=100)
    batch: str = Field(min_length=1, max_length=100)
    plant_id: str = Field(min_length=1, max_length=100)
    layout_version: str = Field(min_length=1, max_length=100)
    measured_at: float
    position: str = Field(max_length=100)
    method: str = Field(min_length=1, max_length=100)
    metric: str = Field(min_length=1, max_length=100)
    value: float
    unit: str = Field(min_length=1, max_length=40)
    corrects: str | None = Field(default=None, max_length=100)


class SafetyApproval(Body):
    config: SafetyConfig


# --- error mapping -----------------------------------------------------------------------------


def refusal(error: Denied) -> JSONResponse:
    status = STATUS_BY_CODE.get(error.code, 403)
    return JSONResponse(
        status_code=status, content={"detail": {"code": error.code, "message": str(error)}}
    )


class GuardedRoute(APIRoute):
    """Turns ``Denied`` raised anywhere in a route (dependencies included) into a response."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            try:
                return await handler(request)
            except Denied as error:
                return refusal(error)

        return guarded


def runtime_json(runtime: StageRuntime) -> dict:
    return runtime.model_dump(mode="json", exclude={"run_sheet"})


VARIABLE_FIELDS = ("id", "label_en", "label_zh", "unit", "method", "min", "max", "deprecated")


def variable_json(variable: Variable) -> dict:
    """What the measurement form needs of a catalog variable."""
    return {name: getattr(variable, name) for name in VARIABLE_FIELDS}


def origin_matches_host(origin: str | None, host: str) -> bool:
    """The Origin must name the very address the request arrived on."""
    if not origin:
        return False
    named = (urlsplit(origin).hostname or "").strip("[]").lower()
    return named == host_only(host).strip("[]")


# --- the workbench -----------------------------------------------------------------------------


class Workbench:
    def __init__(
        self,
        workflow: WorkflowService,
        control: ControlPort,
        archive: Archive,
        operators: Operators,
        settings: Settings,
        role_tokens: Mapping[str, str],
        alerts: AlertBook | None = None,
        tasks: TaskBoard | None = None,
        budget: ProjectBudget | None = None,
        runner: ConfirmatoryRunner | None = None,
        holdout: HoldoutRegistry | None = None,
        compute: ComputeService | None = None,
        conversation: ConversationLog | None = None,
    ):
        self.workflow = workflow
        self.control = control
        self.archive = archive
        self.operators = operators
        self.settings = settings
        self.alerts = alerts
        self.clock = workflow.clock
        for role, token in role_tokens.items():
            if len(token) < MIN_ROLE_TOKEN_LENGTH:
                raise ValueError(
                    f"the token of role {role!r} is shorter than {MIN_ROLE_TOKEN_LENGTH} characters"
                )
        self.roles = dict(role_tokens)
        self.origins = allowed_origins(settings)
        self.router = APIRouter(prefix="/wb", route_class=GuardedRoute)
        self._dependencies()
        self._session_routes()
        self._stage_routes()
        self._intervention_routes()
        self._write_routes()
        self._record_routes()
        self._read_routes()
        reads = (self.router, self.operator, workflow, archive, control, self.clock)
        add_read_routes(*reads, tasks=tasks, budget=budget, alerts=alerts, compute=compute)
        add_round_routes(
            self.router, self.operator, self.fresh, workflow, tasks, budget, archive, conversation
        )
        add_evidence_routes(self.router, self.operator, archive)
        add_manual_task_routes(
            self.router, self.operator, self.on_site, workflow, archive, control, self.clock
        )
        if runner is not None:
            args = (self.router, self.operator, self.fresh, workflow, archive, runner, holdout)
            add_analysis_routes(*args)
        if holdout is not None:
            add_holdout_routes(self.router, self.operator, self.fresh, workflow, holdout)
        if compute is not None and tasks is not None:
            add_compute_routes(self.router, self.operator, self.fresh, compute, tasks)

    # --- who is calling ------------------------------------------------------------------------

    def find_entry(self, request: Request) -> Entry | None:
        """The entry from the listener that accepted the connection and the Host it names."""
        server = request.scope.get("server")
        port = server[1] if server else None
        return entry_for(request.headers.get("host", ""), self.settings, port)

    def entry_of(self, request: Request) -> Entry:
        entry = self.find_entry(request)
        if entry is None:
            raise Denied("entry", "this address is not a registered entry")
        return entry

    def check_browser(self, request: Request) -> None:
        """Same CSRF pattern as the existing UI: allowed Origin plus the UI header."""
        if request.method in SAFE_METHODS:
            return
        origin = request.headers.get("origin")
        host = request.headers.get("host", "")
        allowed = origin in self.origins and origin_matches_host(origin, host)
        if not allowed or request.headers.get("x-growbridge-ui") != "1":
            raise Denied("entry", "the request did not come from the workbench page")

    def model_actor(self, header: str, request: Request) -> Actor:
        scheme, _, value = header.partition(" ")
        matched = None
        for role, token in self.roles.items():  # no early exit: every token is compared
            if hmac.compare_digest(value.strip().encode(), token.encode()):
                matched = role
        if scheme.lower() != "bearer" or matched is None:
            raise Denied("session", "authentication required")
        return Actor(kind="model", id=matched, entry=self.find_entry(request))

    def operator_actor(self, request: Request) -> Actor:
        token = request.cookies.get(COOKIE)
        if not token:
            raise Denied("session", "authentication required")
        self.check_browser(request)
        actor = self.operators.actor(token, self.control.recovery_number())
        if actor.entry is not self.entry_of(request):
            raise Denied("entry", "this session belongs to another entry address")
        return actor

    def _dependencies(self) -> None:
        async def principal(request: Request) -> Actor:
            header = request.headers.get("authorization")
            if header is not None:
                return self.model_actor(header, request)
            return self.operator_actor(request)

        async def operator(actor: Annotated[Actor, Depends(principal)]) -> Actor:
            require_operator(actor, self.clock.now())
            return actor

        async def fresh(actor: Annotated[Actor, Depends(principal)]) -> Actor:
            require_operator(actor, self.clock.now(), recent=True)
            return actor

        async def on_site(actor: Annotated[Actor, Depends(operator)]) -> Actor:
            if actor.entry is not Entry.LAN:
                raise Denied("entry", "this action is only available on the on-site entry")
            return actor

        self.anyone, self.operator, self.fresh, self.on_site = principal, operator, fresh, on_site

    # --- session -------------------------------------------------------------------------------

    def _session_routes(self) -> None:
        router, anyone, operator = self.router, self.anyone, self.operator

        @router.post("/login")
        async def login(request: Request, body: Login, response: Response):
            entry = self.entry_of(request)
            self.check_browser(request)
            recovery = self.control.recovery_number()
            source = request.client.host if request.client else ""
            token = self.operators.login(body.name, body.secret, entry, recovery, source)
            response.set_cookie(
                COOKIE,
                token,
                max_age=SESSION_SECONDS,
                httponly=True,
                samesite="strict",
                secure=entry is Entry.OVERLAY,
                path="/wb",
            )
            return {"operator": body.name, "entry": entry.value, "reauth_seconds": REAUTH_SECONDS}

        @router.post("/logout")
        async def logout(
            request: Request, response: Response, actor: Annotated[Actor, Depends(operator)]
        ):
            self.operators.logout(request.cookies.get(COOKIE, ""))
            response.delete_cookie(COOKIE, path="/wb")
            return {"operator": None}

        @router.post("/reauth")
        async def reauth(
            request: Request, body: Reauth, actor: Annotated[Actor, Depends(operator)]
        ):
            self.operators.reauthenticate(request.cookies.get(COOKIE, ""), body.secret)
            return {"reauth_seconds": REAUTH_SECONDS}

        @router.get("/me")
        async def me(actor: Annotated[Actor, Depends(anyone)]):
            return {
                "kind": actor.kind,
                "id": actor.id,
                "operator": actor.id if actor.kind == "operator" else None,
                "entry": actor.entry.value if actor.entry else None,
                "reauth_at": actor.reauth_at,
                "timezone": self.settings.report_timezone,
            }

    # --- stages --------------------------------------------------------------------------------

    def _stage_routes(self) -> None:
        router, workflow = self.router, self.workflow
        Operator = Annotated[Actor, Depends(self.operator)]  # noqa: N806
        Fresh = Annotated[Actor, Depends(self.fresh)]  # noqa: N806

        @router.post("/stages/{stage_id}/approve")
        async def approve(stage_id: str, actor: Fresh, body: Approve):
            approval = workflow.approve(stage_id, actor, body.expected_digest)
            return approval.model_dump(mode="json")

        @router.post("/stages/{stage_id}/start")
        async def start(stage_id: str, actor: Operator):
            return runtime_json(await workflow.start_stage(stage_id, actor))

        @router.post("/stages/{stage_id}/pause")
        async def pause(stage_id: str, actor: Operator, body: Pause | None = None):
            reason = body.reason if body else Pause().reason
            return runtime_json(await workflow.pause_stage(stage_id, actor, reason))

        @router.post("/stages/{stage_id}/resume")
        async def resume(stage_id: str, actor: Fresh):
            return runtime_json(await workflow.resume_stage(stage_id, actor))

        @router.post("/stages/{stage_id}/stop")
        async def stop(stage_id: str, actor: Operator):
            return runtime_json(await workflow.stop_stage(stage_id, actor))

    def _intervention_routes(self) -> None:
        router, workflow = self.router, self.workflow
        Operator = Annotated[Actor, Depends(self.operator)]  # noqa: N806
        Fresh = Annotated[Actor, Depends(self.fresh)]  # noqa: N806

        @router.post("/stages/{stage_id}/takeover")
        async def takeover(stage_id: str, actor: Fresh):
            return runtime_json(await workflow.takeover(stage_id, actor))

        @router.post("/stages/{stage_id}/handback")
        async def handback(stage_id: str, actor: Operator, body: Handback | None = None):
            accept = body.accept_as_intervention if body else False
            runtime, differences = await workflow.handback(stage_id, actor, accept)
            return {
                "stage": runtime_json(runtime),
                "differences": [item.model_dump(mode="json") for item in differences],
            }

        @router.post("/stages/{stage_id}/onsite-check")
        async def onsite_check(stage_id: str, body: Note, actor: Operator):
            return runtime_json(await workflow.record_onsite_check(stage_id, actor, body.note))

        @router.post("/drafts/run-sheet")
        async def draft(body: Draft, actor: Annotated[Actor, Depends(self.anyone)]):
            findings = workflow.submit_run_sheet(body.round_id, body.run_sheet, actor)
            return {
                "stage_id": body.run_sheet.stage_id,
                "findings": [item.model_dump(mode="json") for item in findings],
            }

    # --- device writes by the operator ---------------------------------------------------------

    def manual_stage(self, stage_id: str) -> StageRuntime:
        stage = self.workflow.stage(stage_id)
        if stage.state is not StageState.MANUAL or stage.manual_right is None:
            raise Denied("state", "the stage is not under manual control")
        return stage

    def action_request(
        self, body: ManualWrite | Irrigation, stage: StageRuntime, actor: Actor, channel, level
    ) -> ActionRequest:
        note = body.note.strip()
        return ActionRequest(
            request_id=body.request_id,
            right_number=stage.manual_right or 0,
            channel=channel,
            level=level,
            trigger=f"manual: {note}" if note else "manual",
            experiment_id=stage.experiment_id,
            stage_id=stage.stage_id,
            operator=actor.id,
        )

    def _write_routes(self) -> None:
        router = self.router
        Operator = Annotated[Actor, Depends(self.operator)]  # noqa: N806
        OnSite = Annotated[Actor, Depends(self.on_site)]  # noqa: N806

        @router.post("/manual/{channel}")
        async def manual(channel: Channel, body: ManualWrite, actor: Operator):
            try:
                check_level(channel, body.level)
            except ValueError as error:
                raise rejected(str(error)) from error
            if channel is Channel.PUMP and body.level != 0:
                raise Denied("pump_on_forbidden", "the pump is only started by an irrigation run")
            stage = self.manual_stage(body.stage_id)
            request = self.action_request(body, stage, actor, channel, body.level)
            return (await self.control.submit(request)).model_dump(mode="json")

        @router.post("/irrigation")
        async def irrigation(body: Irrigation, actor: OnSite):
            stage = self.manual_stage(body.stage_id)
            request = self.action_request(body, stage, actor, Channel.PUMP, 1)
            record = await self.control.irrigate(request, body.seconds)
            return record.model_dump(mode="json")

    # --- records -------------------------------------------------------------------------------

    def staged_experiment(self, experiment_id: str) -> None:
        """Refuses an experiment no stage runs: every measurement must trace to a project."""
        if not self.workflow.store.projects_of_experiment(experiment_id):
            raise Denied("scope", "a measurement belongs to an experiment of an existing stage")

    def _record_routes(self) -> None:
        router = self.router
        Operator = Annotated[Actor, Depends(self.operator)]  # noqa: N806
        Fresh = Annotated[Actor, Depends(self.fresh)]  # noqa: N806

        @router.post("/measurements")
        async def measurement(body: MeasurementIn, actor: Operator):
            self.staged_experiment(body.experiment_id)
            fields = body.model_dump(exclude={"id"})
            try:
                record = ManualMeasurement(
                    id=body.id or new_id("measurement"), operator=actor.id, **fields
                )
            except ValueError as error:
                raise rejected("the measurement was not accepted") from error
            declared = self.workflow.store.declared_variables(body.experiment_id)
            problems = check_measurement(record, self.workflow.catalog, declared)
            if problems:
                raise rejected("; ".join(problems))
            try:
                self.archive.add_measurement(record)
            except ValueError as error:
                raise rejected("the measurement was not accepted") from error
            return {"id": record.id}

        @router.post("/safety/approve")
        async def approve_safety(body: SafetyApproval, actor: Fresh):
            stamp = {"approved_by": actor.id, "approved_at": self.clock.now()}
            number = self.control.approve_safety(body.config.model_copy(update=stamp), actor.id)
            return {"protection_right": number}

    # --- reads ---------------------------------------------------------------------------------

    def _read_routes(self) -> None:
        router, anyone = self.router, self.anyone
        Anyone = Annotated[Actor, Depends(anyone)]  # noqa: N806

        @router.get("/stages/{stage_id}")
        async def stage(stage_id: str, actor: Anyone):
            runtime = self.workflow.stage(stage_id)
            body = runtime_json(runtime)
            if actor.kind != "operator":
                # Models get the stage as they always did (project id included) but not its round:
                # naming the round would let a model aim a run-sheet draft at it.
                return body
            store = self.workflow.store
            row = store.find_stage(stage_id)  # the runtime does not name its round
            return {
                **body,
                "round_id": row.round_id if row else None,
                "state_at": row.state_at if row else None,  # the console proves a finished window
                "project_id": row.project_id if row else runtime.project_id,
                **(stage_names(store, row) if row else dict.fromkeys(STAGE_NAME_KEYS)),
            }

        @router.get("/experiments/{experiment_id}/variables")
        async def variables(experiment_id: str, actor: Anyone):
            """The variables a measurement of this experiment may name, as the entry form offers:
            the declared manual ones (a declared sensor or factor variable is always refused)."""
            self.staged_experiment(experiment_id)
            declared = self.workflow.store.declared_variables(experiment_id)
            entries = (self.workflow.catalog.get(name) for name in sorted(declared))
            manual = [entry for entry in entries if entry is not None and entry.kind == "manual"]
            return {
                "experiment_id": experiment_id,
                "variables": [variable_json(entry) for entry in manual],
            }

        @router.get("/receipts/{request_id}")
        async def receipt(request_id: str, actor: Anyone):
            record = self.control.receipt(request_id)
            if record is None:
                raise HTTPException(404, "Unknown request id")
            return record.model_dump(mode="json")

        if self.alerts is not None:
            self._alert_routes()

    def _alert_routes(self) -> None:
        router, book = self.router, self.alerts
        assert book is not None

        @router.get("/alerts")
        async def alerts(actor: Annotated[Actor, Depends(self.anyone)]):
            return {"alerts": [item.model_dump(mode="json") for item in book.open()]}

        @router.post("/alerts/{event_id}/read")
        async def mark_read(event_id: str, actor: Annotated[Actor, Depends(self.operator)]):
            book.mark_read(event_id, actor)
            return {"event_id": event_id}


def create_workbench(
    workflow: WorkflowService,
    control: ControlPort,
    archive: Archive,
    operators: Operators,
    settings: Settings,
    role_tokens: Mapping[str, str],
    alerts: AlertBook | None = None,
    tasks: TaskBoard | None = None,
    budget: ProjectBudget | None = None,
    runner: ConfirmatoryRunner | None = None,
    holdout: HoldoutRegistry | None = None,
    compute: ComputeService | None = None,
    conversation: ConversationLog | None = None,
) -> APIRouter:
    """The ``/wb`` router. ``alerts`` adds the alert list and mark-as-read routes when given;
    ``tasks`` and ``budget`` together add the call budget and research goal routes; ``runner``
    adds the analysis freeze and run routes (``holdout`` guards what they may analyse);
    ``compute`` (with ``tasks``) adds the balance and task budget routes; ``conversation`` (with
    the goal routes) records each goal and adds the project conversation read."""
    args = (workflow, control, archive, operators, settings, role_tokens)
    more = (alerts, tasks, budget, runner, holdout, compute, conversation)
    return Workbench(*args, *more).router
