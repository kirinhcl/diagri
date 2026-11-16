"""The copy of each workflow intervention into the archive (split out of ``runtime``)."""

import hashlib
import json
import logging

from growbridge.archive.db import Database
from growbridge.archive.store import Archive
from growbridge.observer.alerts import AlertHook

log = logging.getLogger(__name__)

MIRROR_NAMESPACE = "runtime_mirror"
MIRROR_STEPS = ("CREATE TABLE intervention_mirror(key TEXT PRIMARY KEY, record_id TEXT NOT NULL)",)


class InterventionMirror:
    """Copies each workflow intervention into the archive exactly once.

    The key is a digest of the intervention's content, kept in a table of the archive database
    so the copy and its key are saved together; a repeat (restart, replay) finds the key.
    """

    def __init__(self, db: Database, archive: Archive):
        self.db = db
        self.archive = archive
        self.alert: AlertHook | None = None
        db.migrate(MIRROR_NAMESPACE, MIRROR_STEPS)

    def __call__(self, item: dict) -> None:
        try:
            self._mirror(item)
        except Exception as error:
            log.exception("intervention could not be copied to the archive")
            if self.alert is not None:
                message = f"{item.get('kind')} not copied to the archive: {error}"
                self.alert("intervention_mirror", "archive", message)

    def _mirror(self, item: dict) -> None:
        key = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
        with self.db.transaction():
            if self.db.one("SELECT 1 FROM intervention_mirror WHERE key = ?", (key,)):
                return
            record_id = self.archive.record_intervention(
                item["experiment_id"],
                item["stage_id"],
                item["kind"],
                item["detail"],
                item["operator"],
            )
            self.db.execute("INSERT INTO intervention_mirror VALUES (?, ?)", (key, record_id))
