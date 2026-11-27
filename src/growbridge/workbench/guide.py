"""The routes of the guided protocol setup, under ``/wb/guide``.

A session belongs to the operator who started it and to that operator's project: others get the
answer for a session that does not exist, and only the owner may change it. Nothing here asks a
model; every option comes from the system and every answer is checked by the rules the save route
applies. The protocol itself is still saved by ``POST /wb/protocols``: the ``saved`` route only
records which saved version the session ended in and what the researcher changed on the way.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal, NamedTuple

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from growbridge.archive.models import ResearchProtocol
from growbridge.guide.compose import (
    compose,
    edited_fields,
    new_protocol_id,
    next_version,
    review,
)
from growbridge.guide.draft import carried_answers, latest_chosen, step_states
from growbridge.guide.options import options_for
from growbridge.guide.steps import ANSWERED, StepId, answer_problems, parse_answer
from growbridge.guide.store import GuideEvent, GuideSession, GuideStore
from growbridge.planning.design import estimate_sample_size
from growbridge.ports import Actor, Denied
from growbridge.workbench.common import Body, rejected
from growbridge.workbench.rounds import Ident, PathId
from growbridge.workbench.scope import project_read, project_write
from growbridge.workflow import denials
from growbridge.workflow.access import Access
from growbridge.workflow.service import WorkflowService

Dependency = Callable[..., Awaitable[Actor]]
MESSAGE_CHARS = 500


class GuideStartIn(Body):
    project_id: Ident
    lang: Literal["en", "zh"] = "zh"


class ChooseIn(Body):
    answer: dict[str, Any]
    option_ids: tuple[str, ...] = ()


class SavedIn(Body):
    protocol_id: Ident
    version: int = Field(ge=1)


class _Base(NamedTuple):
    """The protocol a session's draft becomes a version of."""

    protocol_id: str
    version: int
    declared_before: frozenset[str]


def _invalid(step: str, message: str):
    return rejected(message[:MESSAGE_CHARS], reason="guide_answer_invalid", params={"step": step})


class _Guide:
    def __init__(self, workflow: WorkflowService, guide: GuideStore, access: Access | None):
        self.workflow, self.guide, self.access = workflow, guide, access

    # --- who may see and change a session ------------------------------------------------------

    def session(self, session_id: str, actor: Actor, *, write: bool) -> GuideSession:
        unknown = denials.unknown("guide session", session_id)
        found = self.guide.session(session_id)
        if found is None:
            raise unknown
        check = project_write if write else project_read
        check(self.access, actor, found.project_id, lambda: unknown)
        if write and found.operator != actor.id:
            raise Denied("state", "another operator started this guide", reason="guide_not_owner")
        return found

    # --- the protocol a session builds ---------------------------------------------------------

    def base(self, session: GuideSession, events: tuple[GuideEvent, ...]) -> _Base:
        rows = self.workflow.store.project_protocols(session.project_id)
        protocol_id = self._known_id(events)
        if protocol_id is None:
            taken = tuple(dict.fromkeys(row[0] for row in rows))  # as the web form counts them
            protocol_id = new_protocol_id(session.project_id, taken, len(taken))
        version = next_version([v for pid, v in rows if pid == protocol_id])
        before = self.workflow.store.protocol_variables_before(protocol_id, version)
        return _Base(protocol_id, version, before)

    @staticmethod
    def _known_id(events: tuple[GuideEvent, ...]) -> str | None:
        for event in reversed(events):
            if event.kind == "saved":
                return event.payload["protocol_id"]
        for event in events:
            origin = event.payload.get("carried_from")
            if event.kind == "chosen" and origin:
                return origin["protocol_id"]
        return None

    def edited(
        self, session: GuideSession, events: tuple[GuideEvent, ...], saved: ResearchProtocol
    ) -> list[str]:
        """What differs between the saved version and what the choices make; every top-level
        field when the choices no longer make a protocol."""
        try:
            composed = compose(
                latest_chosen(events),
                project_id=session.project_id,
                protocol_id=saved.id,
                version=saved.version,
                seed=session.seed,
            )
        except ValueError:
            return sorted(ResearchProtocol.model_fields)
        return list(edited_fields(composed, saved))

    # --- what the routes answer ----------------------------------------------------------------

    def view(self, session: GuideSession) -> dict[str, Any]:
        events = self.guide.events(session.session_id)
        return {
            "session": session.model_dump(mode="json"),
            "steps": [state.model_dump(mode="json") for state in step_states(events)],
            "saved": [
                {key: e.payload[key] for key in ("protocol_id", "version", "digest", "edited")}
                for e in events
                if e.kind == "saved"
            ],
        }

    def start(self, project_id: str, lang: Literal["en", "zh"], actor: Actor) -> str:
        unknown = denials.unknown("project", project_id)
        if not self.workflow.store.has_project(project_id):
            raise unknown
        project_write(self.access, actor, project_id, lambda: unknown)
        session = self.guide.start(project_id, actor.id, lang)
        rows = self.workflow.store.project_protocols(project_id)
        if rows:
            self._carry(session, *rows[-1], actor)
        return session.session_id

    def _carry(self, session: GuideSession, protocol_id: str, version: int, actor: Actor) -> None:
        protocol = self.workflow.store.protocol(protocol_id, version)
        if protocol is None:
            return
        origin = {"protocol_id": protocol_id, "version": version}
        items = [
            (
                step,
                "chosen",
                {"answer": answer, "source": "carried", "option_ids": [], "carried_from": origin},
            )
            for step, answer in carried_answers(protocol).items()
        ]
        self.guide.append_many(session.session_id, items, actor.id)

    def choose(
        self, session: GuideSession, step: StepId, body: ChooseIn, actor: Actor
    ) -> dict[str, Any]:
        events = self.guide.events(session.session_id)
        offered = options_for(step, self.workflow.catalog, session.seed)
        if step not in ANSWERED or not set(body.option_ids) <= {o.id for o in offered.options}:
            raise _invalid(step, "that choice was not offered for this step")
        declared = self.base(session, events).declared_before
        answer = self._checked(step, body.answer, declared)
        source = "system" if body.option_ids else "own"
        chosen = {"answer": answer, "source": source, "option_ids": list(body.option_ids)}
        offer = {"options": [o.model_dump(mode="json") for o in offered.options]}
        self.guide.append_many(
            session.session_id, [(step, "offered", offer), (step, "chosen", chosen)], actor.id
        )
        return self.view(session)

    def _checked(self, step: StepId, raw: dict[str, Any], declared: frozenset[str]):
        try:
            answer = parse_answer(step, raw)
        except ValueError as exc:
            raise _invalid(step, str(exc)) from None
        problems = answer_problems(step, answer, self.workflow.catalog, declared)
        if problems:
            raise _invalid(step, "; ".join(problems))
        return answer.model_dump(mode="json")

    def review(self, session: GuideSession) -> dict[str, Any]:
        events = self.guide.events(session.session_id)
        base = self.base(session, events)
        found = review(
            latest_chosen(events),
            project_id=session.project_id,
            protocol_id=base.protocol_id,
            version=base.version,
            seed=session.seed,
            catalog=self.workflow.catalog,
            declared_before=base.declared_before,
        )
        return {
            **found.model_dump(mode="json"),
            "protocol_id": base.protocol_id,
            "version": base.version,
        }

    def saved(self, session: GuideSession, body: SavedIn, actor: Actor) -> dict[str, Any]:
        protocol = self.workflow.store.protocol(body.protocol_id, body.version)
        if protocol is None or protocol.project_id != session.project_id:
            raise denials.unknown("protocol", body.protocol_id)
        events = self.guide.events(session.session_id)
        payload = {
            "protocol_id": protocol.id,
            "version": protocol.version,
            "digest": protocol.digest(),
            "edited": self.edited(session, events, protocol),
        }
        self.guide.append(session.session_id, "review", "saved", payload, actor.id)
        return self.view(session)


def add_guide_routes(
    router: APIRouter,
    operator: Dependency,
    workflow: WorkflowService,
    guide: GuideStore,
    access: Access | None = None,
) -> None:
    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806
    run = _Guide(workflow, guide, access)

    @router.post("/guide/sessions")
    async def start_session(body: GuideStartIn, actor: Operator):
        return {"session_id": run.start(body.project_id, body.lang, actor)}

    @router.get("/guide/sessions/{session_id}")
    async def read_session(session_id: PathId, actor: Operator):
        return run.view(run.session(session_id, actor, write=False))

    @router.get("/guide/sessions/{session_id}/steps/{step}")
    async def step_options(session_id: PathId, step: StepId, actor: Operator):
        found = run.session(session_id, actor, write=False)
        return options_for(step, workflow.catalog, found.seed).model_dump(mode="json")

    @router.post("/guide/sessions/{session_id}/steps/{step}/choose")
    async def choose_step(session_id: PathId, step: StepId, body: ChooseIn, actor: Operator):
        return run.choose(run.session(session_id, actor, write=True), step, body, actor)

    @router.post("/guide/sessions/{session_id}/steps/{step}/reopen")
    async def reopen_step(session_id: PathId, step: StepId, actor: Operator):
        found = run.session(session_id, actor, write=True)
        guide.append(session_id, step, "reopened", {}, actor.id)
        return run.view(found)

    @router.get("/guide/sessions/{session_id}/review")
    async def review_session(session_id: PathId, actor: Operator):
        return run.review(run.session(session_id, actor, write=False))

    @router.get("/guide/sample-size")
    async def sample_size(
        actor: Operator,
        effect: Annotated[float, Query(gt=0, allow_inf_nan=False)],
        sd: Annotated[float, Query(gt=0, allow_inf_nan=False)],
        design: Literal["paired_block", "two_group"],
    ):
        return {"n": estimate_sample_size(effect, sd, design=design), "design": design}

    @router.post("/guide/sessions/{session_id}/saved")
    async def record_saved(session_id: PathId, body: SavedIn, actor: Operator):
        return run.saved(run.session(session_id, actor, write=True), body, actor)
