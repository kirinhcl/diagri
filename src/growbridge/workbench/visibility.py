"""Every GET route of the workbench and the visibility rule it follows (multi-user).

``tests/workbench/test_workbench_multi_user_reads.py`` fails when a GET route is missing here, and
checks each rule's routes with two operators. A new read route needs an entry and a check.

- project, stage, round, receipt: the object's project owner (and administrators); anyone else
  gets the route's own answer for an id that does not exist.
- device: the lock holder of the local greenhouse (and administrators).
- alerts, inbox, compute: filtered item by item.
- public: every signed-in operator (evidence cards are literature, and the device's capabilities
  are the hardware's fixed ranges the forms check against: neither is anyone's data).
- self: the caller's own session and locks. admin: administrators only.
"""

READ_RULES: dict[str, str] = {
    "/wb/alerts": "alerts",
    "/wb/compute": "compute",
    "/wb/devices/{device_id}/notes": "device",
    "/wb/environment": "device",
    "/wb/capabilities": "public",
    "/wb/evidence": "public",
    "/wb/evidence/relations": "public",
    "/wb/experiments/{experiment_id}/variables": "project",
    "/wb/holdouts": "project",
    "/wb/inbox": "inbox",
    "/wb/me": "self",
    "/wb/projects": "project",
    "/wb/projects/{project_id}": "project",
    "/wb/projects/{project_id}/conversation": "project",
    "/wb/protocols/{protocol_id}/analysis": "project",
    "/wb/receipts/{request_id:path}": "receipt",
    "/wb/rounds/{round_id}": "round",
    "/wb/rounds/{round_id}/report": "round",
    "/wb/safety": "device",
    "/wb/stages/{stage_id}": "stage",
    "/wb/stages/{stage_id}/history": "stage",
    "/wb/stages/{stage_id}/manual-tasks": "stage",
    "/wb/stages/{stage_id}/measurements": "stage",
    "/wb/stages/{stage_id}/readings": "stage",
    "/wb/stages/{stage_id}/run-sheet": "stage",
    "/wb/greenhouses": "self",
    "/wb/admin/operators": "admin",
    "/wb/admin/locks": "admin",
}
