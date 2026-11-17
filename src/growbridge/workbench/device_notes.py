"""Notes about the device (memory design 2026-11-17, section 5.6): the lock holder of the
greenhouse and administrators read and write them; models only read them as background."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from growbridge.observer.device_notes import NOTE_MAX, DeviceNotes
from growbridge.ports import Actor, Denied
from growbridge.workflow.access import Access

SENSOR_MAX = 40


class DeviceNoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=NOTE_MAX)
    sensor: str | None = Field(default=None, max_length=SENSOR_MAX)


def add_device_note_routes(
    router: APIRouter,
    operator,
    notes: DeviceNotes | None,
    access: Access | None,
    local_device: str,
) -> None:
    Operator = Annotated[Actor, Depends(operator)]  # noqa: N806

    def check(actor: Actor, device_id: str) -> None:
        if device_id != local_device:
            raise Denied("state", f"unknown device {device_id}")
        if access is not None and not access.sees_device(actor, device_id):
            raise Denied("not_lock_holder", "lock this greenhouse to read or write its notes")

    @router.get("/devices/{device_id}/notes")
    async def device_notes(device_id: str, actor: Operator):
        check(actor, device_id)
        found = () if notes is None else notes.recent(device_id)
        return {"notes": [note.model_dump(mode="json") for note in found]}

    @router.post("/devices/{device_id}/notes")
    async def add_device_note(device_id: str, body: DeviceNoteInput, actor: Operator):
        check(actor, device_id)
        if notes is None:
            raise Denied("state", "device notes are not available")
        return notes.add(device_id, actor.id, body.text, body.sensor).model_dump(mode="json")
