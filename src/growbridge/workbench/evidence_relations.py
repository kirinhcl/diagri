"""Workbench routes of relations between evidence cards (supersedes, contradicts, retracts).

An operator records a relation (confirmed at once), confirms or rejects a model's proposal,
withdraws a confirmed one, and lists them. Operators only: a model role is refused with
``model_role``. Each route acts in one project (or none, for public cards): the writes need that
project's owner, the listing needs it to be visible, and an id the caller may not see is
answered as an unknown one.

A relation a model proposed in project P is shown to other projects only once confirmed, and
then without its task and with the reviewer's note in place of the model's reason (the model's
text may name P's own cards).
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends

from growbridge.archive.evidence_book import card_project
from growbridge.archive.evidence_ledger import RelationKind, RelationRecord
from growbridge.archive.evidence_relations import (
    Note,
    Reason,
    RelationRefused,
    RelationRequest,
    as_denied,
    check_request,
    record_relation,
    relation_not_found,
    relation_scope,
    review_relation,
    unknown_card,
    withdraw_relation,
)
from growbridge.archive.store import Archive
from growbridge.ports import Actor
from growbridge.workbench.common import Body
from growbridge.workbench.rounds import PathId
from growbridge.workbench.scope import project_read, project_write
from growbridge.workflow import denials
from growbridge.workflow.access import Access, Hidden

Dependency = Callable[..., Awaitable[Actor]]


class RelationIn(Body):
    kind: RelationKind
    card_id: str
    other_card_id: str | None = None
    reason: Reason


class ReviewIn(Body):
    decision: Literal["confirmed", "rejected"]
    note: Note = ""


class WithdrawIn(Body):
    reason: Reason


def relation_json(record: RelationRecord, viewer: str | None) -> dict:
    """The record as shown to ``viewer``'s project (None: the global view)."""
    data = record.model_dump(mode="json")
    home = record.relation.proposed_in
    if home is not None and home != viewer:
        note = record.review.note if record.review is not None else ""
        data["relation"] = {
            **data["relation"],
            "task_id": None,
            "reason": note,
            "proposed_in": None,
        }
    return {**data, "state": record.state}


class RelationRoutes:
    def __init__(self, archive: Archive, access: Access | None = None):
        self.archive = archive
        self.access = access

    def _hidden(self, project_id: str):
        return lambda: denials.unknown("project", project_id)

    def _write_guard(
        self, actor: Actor, project_id: str | None, hidden: Hidden | None = None
    ) -> None:
        if project_id is not None:
            project_write(self.access, actor, project_id, hidden or self._hidden(project_id))

    @staticmethod
    def _unknown(relation_id: str) -> Hidden:
        return lambda: as_denied(relation_not_found(relation_id))

    def _record(self, relation_id: str) -> RelationRecord:
        record = self.archive.ledger.record(relation_id)
        if record is None:
            raise as_denied(relation_not_found(relation_id))
        return record

    def _check_cards_seen(self, actor: Actor, request: RelationRequest) -> None:
        """A card of a project the caller cannot see is refused as a card that does not exist,
        before the cards' scope is looked at, so neither the card nor its project is revealed."""
        if self.access is None:
            return
        for card_id in (request.card_id, request.other_card_id):
            project = None if card_id is None else card_project(self.archive, card_id)
            if project is not None and not self.access.sees_project(actor, project):
                raise unknown_card(card_id or "")

    def record(self, body: RelationIn, actor: Actor) -> dict:
        request = RelationRequest(**body.model_dump())
        try:
            check_request(request)
            self._check_cards_seen(actor, request)
            project = relation_scope(self.archive, request)
            self._write_guard(actor, project)
            made = record_relation(self.archive, request, actor.id, project)
        except RelationRefused as error:
            raise as_denied(error) from None
        return relation_json(made, project)

    def review(self, relation_id: str, body: ReviewIn, actor: Actor) -> dict:
        relation = self._record(relation_id).relation
        project = relation.project_id or relation.proposed_in
        self._write_guard(actor, project, self._unknown(relation_id))
        try:
            done = review_relation(
                self.archive, relation_id, body.decision, actor.id, body.note, project
            )
        except RelationRefused as error:
            raise as_denied(error) from None
        return relation_json(done, project)

    def withdraw(self, relation_id: str, body: WithdrawIn, actor: Actor) -> dict:
        project = self._record(relation_id).relation.project_id
        self._write_guard(actor, project, self._unknown(relation_id))
        try:
            done = withdraw_relation(self.archive, relation_id, actor.id, body.reason, project)
        except RelationRefused as error:
            raise as_denied(error) from None
        return relation_json(done, project)

    def listing(self, actor: Actor, project_id: str | None = None) -> dict:
        if project_id is not None:
            project_read(self.access, actor, project_id, self._hidden(project_id))
        rows = [
            relation_json(r, project_id)
            for r in self.archive.ledger.records(project_id)
            if not _foreign_proposal(r, project_id)
        ]
        return {"relations": rows}


def _foreign_proposal(record: RelationRecord, viewer: str | None) -> bool:
    """A pending or rejected proposal of another project is not the viewer's to see."""
    return record.state in ("pending", "rejected") and record.relation.proposed_in not in (
        None,
        viewer,
    )


def add_evidence_relation_routes(
    router: APIRouter, operator: Dependency, archive: Archive, access: Access | None = None
) -> None:
    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806
    routes = RelationRoutes(archive, access)

    @router.post("/evidence/relations")
    async def record_one(body: RelationIn, actor: Operator):
        return routes.record(body, actor)

    @router.post("/evidence/relations/{relation_id}/review")
    async def review_one(relation_id: PathId, body: ReviewIn, actor: Operator):
        return routes.review(relation_id, body, actor)

    @router.post("/evidence/relations/{relation_id}/withdraw")
    async def withdraw_one(relation_id: PathId, body: WithdrawIn, actor: Operator):
        return routes.withdraw(relation_id, body, actor)

    @router.get("/evidence/relations")
    async def list_relations(actor: Operator, project_id: str | None = None):
        return routes.listing(actor, project_id)
