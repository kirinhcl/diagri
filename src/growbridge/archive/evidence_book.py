"""Which evidence cards a project can see, and their status as seen from that project.

Public cards (no origin) are visible everywhere; a round card belongs to the project of its
origin and is visible only there.
"""

from collections.abc import Iterable

from growbridge.archive.evidence_ledger import EvidenceOrigin
from growbridge.archive.evidence_status import CardStatus, derive_statuses
from growbridge.archive.models import EvidenceCard
from growbridge.archive.store import Archive


def card_project(archive: Archive, card_id: str) -> str | None:
    """The project a round card belongs to; None for a public card."""
    origin = archive.ledger.origin(card_id)
    return None if origin is None else origin.project_id


def visible_cards(archive: Archive, project_id: str | None) -> dict[str, EvidenceCard]:
    """Public cards plus the project cards of ``project_id``."""
    origins = archive.ledger.origins()
    return {
        card.id: card
        for card in archive.evidence()
        if card.id not in origins or origins[card.id].project_id == project_id
    }


def _invalid_at(
    archive: Archive, origins: Iterable[EvidenceOrigin]
) -> dict[str, tuple[float, str]]:
    found: dict[str, tuple[float, str]] = {}
    for origin in origins:
        hit = archive.invalidated_at([origin.report_artifact_id, *origin.snapshot_ids])
        if hit is not None:
            found[origin.card_id] = hit
    return found


def card_statuses(
    archive: Archive,
    card_ids: Iterable[str],
    project_id: str | None,
    as_of: float | None = None,
) -> dict[str, CardStatus]:
    """Status of each requested card that is visible in ``project_id``, as of ``as_of``.

    Invalidity is computed for every visible round card, since a supersede chain may end on one."""
    visible = visible_cards(archive, project_id)
    wanted = [card_id for card_id in card_ids if card_id in visible]
    origins = archive.ledger.origins()
    invalid_at = _invalid_at(archive, (origins[c] for c in visible if c in origins))
    statuses = derive_statuses(
        wanted,
        archive.ledger.records(project_id),
        invalid_at,
        archive.clock.now() if as_of is None else as_of,
        project_id,
    )
    return {card_id: statuses[card_id] for card_id in wanted}
