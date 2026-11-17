"""Notes people write about a device: a probe changed, a loose wire, a fan cleaned.

They are about the device, not anyone's experiment, and are written for whoever uses the
greenhouse later. Models read them as background (``agents/memory.py``) and never write them.
"""

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.archive.models import Model
from growbridge.ports import Denied

NAMESPACE = "device_notes"
STEPS = (
    "CREATE TABLE device_notes(id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT NOT NULL,"
    " at REAL NOT NULL, actor TEXT NOT NULL, sensor TEXT, text TEXT NOT NULL)",
    "CREATE INDEX device_notes_by_time ON device_notes(device_id, at)",
)
NOTE_MAX = 500


class DeviceNote(Model):
    id: int
    device_id: str
    at: float
    actor: str
    sensor: str | None = None
    text: str


class DeviceNotes:
    def __init__(self, db: Database, clock: Clock):
        self.db = db
        self.clock = clock
        db.migrate(NAMESPACE, STEPS)

    def add(self, device_id: str, actor: str, text: str, sensor: str | None = None) -> DeviceNote:
        body = text.strip()
        message = f"a device note has 1 to {NOTE_MAX} characters"
        if not body:
            raise Denied("param", message, reason="param_required", params={"field": "text"})
        if len(body) > NOTE_MAX:
            params = {"field": "text", "max_length": NOTE_MAX}
            raise Denied("param", message, reason="param_too_long", params=params)
        cursor = self.db.execute(
            "INSERT INTO device_notes(device_id, at, actor, sensor, text) VALUES (?, ?, ?, ?, ?)",
            (device_id, self.clock.now(), actor, sensor, body),
        )
        row = self.db.one("SELECT * FROM device_notes WHERE id = ?", (cursor.lastrowid,))
        return DeviceNote(**dict(row))

    def recent(
        self, device_id: str, since: float | None = None, limit: int = 10
    ) -> tuple[DeviceNote, ...]:
        """The newest notes of the device first, written at or after ``since``."""
        rows = self.db.query(
            "SELECT * FROM device_notes WHERE device_id = ? AND at >= ?"
            " ORDER BY at DESC, id DESC LIMIT ?",
            (device_id, float("-inf") if since is None else since, limit),
        )
        return tuple(DeviceNote(**dict(row)) for row in rows)
