"""Starting and steering a research round through the workbench: project, protocol, round, call
budget, goal, run sheet review, the choice after a stopped stage, and abort. Operators only."""

import json

import pytest
from fastapi.testclient import TestClient
from workbench_support import LAN_HOST, LAN_PORT, ROLE_TOKENS, SECRET

from growbridge.agents.handlers_orchestrator import DEFAULT_TASK_BUDGET
from growbridge.agents.handlers_orchestrator import ROLE as ORCHESTRATOR
from growbridge.api import create_app
from growbridge.archive.models import Budget
from growbridge.ports import Denied, Finding
from growbridge.sim.fixtures import make_protocol
from growbridge.workbench.api import create_workbench
from growbridge.workflow.states import RoundState, TaskState

GOAL = "does more light speed up canopy growth?"
COOKIE = "growbridge_operator"
TABLES = ("wf_projects", "wf_protocols", "wf_rounds", "task_board", "call_budget")
ROUTES = (
    "create project",
    "save protocol",
    "create round",
    "set budget",
    "submit goal",
    "choose after stop",
    "abort round",
    "read round",
    "read run sheet",
)
WRITES = tuple(name for name in ROUTES if not name.startswith("read"))


def detail(response) -> dict:
    return response.json()["detail"]


def protocol_json(project_id: str, **fields) -> dict:
    protocol = make_protocol(project_id=project_id, stages=("vegetative",), **fields)
    return protocol.model_dump(mode="json")


def designed(bench, client, protocol_id: str = "protocol-1") -> tuple[str, str]:
    """A project, its protocol and a round, all made through the routes."""
    project = bench.post(client, "/wb/projects", {"name": "lettuce light series"})
    project_id = project.json()["project_id"]
    protocol = protocol_json(project_id, id=protocol_id)
    assert bench.post(client, "/wb/protocols", {"protocol": protocol}).status_code == 200
    body = {"project_id": project_id, "protocol_id": protocol_id}
    return project_id, bench.post(client, "/wb/rounds", body).json()["round_id"]


def set_budget(bench, client, project_id: str, calls: int = 50, cost: float = 100.0):
    body = {"max_calls": calls, "max_cost": cost}
    return bench.post(client, f"/wb/projects/{project_id}/budget", body)


def funded(bench, client) -> tuple[str, str]:
    project_id, round_id = designed(bench, client)
    assert set_budget(bench, client, project_id).status_code == 200
    return project_id, round_id


def running(bench, client) -> None:
    bench.pending()
    assert bench.approve(client).status_code == 200
    assert bench.post(client, "/wb/stages/stage-1/start").status_code == 200


def stopped(bench, client) -> None:
    running(bench, client)
    assert bench.post(client, "/wb/stages/stage-1/stop").status_code == 200


def choose(bench, client, choice: str):
    return bench.post(client, f"/wb/rounds/{bench.round_id}/choice", {"choice": choice})


def round_view(bench, client) -> dict:
    return client.get(f"/wb/rounds/{bench.round_id}").json()


def draft(bench, client, stage_id: str):
    sheet = bench.sheet(stage_id).model_dump(mode="json")
    body = {"round_id": bench.round_id, "run_sheet": sheet}
    return bench.post(client, "/wb/drafts/run-sheet", body)


def route(bench, name: str) -> tuple[str, str, dict | None]:
    project, round_id = bench.project_id, bench.round_id
    table = {
        "create project": ("post", "/wb/projects", {"name": "another series"}),
        "save protocol": ("post", "/wb/protocols", {"protocol": protocol_json(project, version=2)}),
        "create round": (
            "post",
            "/wb/rounds",
            {"project_id": project, "protocol_id": "protocol-1"},
        ),
        "set budget": ("post", f"/wb/projects/{project}/budget", {"max_calls": 5, "max_cost": 1.0}),
        "submit goal": ("post", "/wb/goals", {"project_id": project, "goal": GOAL}),
        "choose after stop": ("post", f"/wb/rounds/{round_id}/choice", {"choice": "abort"}),
        "abort round": ("post", f"/wb/rounds/{round_id}/abort", None),
        "read round": ("get", f"/wb/rounds/{round_id}", None),
        "read run sheet": ("get", "/wb/stages/stage-1/run-sheet", None),
    }
    return table[name]


def send(bench, client, name: str, headers: dict | None = None, ui: bool = True):
    method, path, body = route(bench, name)
    if method == "get":
        return client.get(path, headers=headers or {})
    page = bench.ui(client) if ui else {}
    return client.post(path, json=body or {}, headers={**page, **(headers or {})})


def rows(bench, table: str) -> int:
    return bench.db.one(f"SELECT COUNT(*) AS n FROM {table}")["n"]


def raw_post(bench, client, path: str, body: dict):
    """Like ``bench.post``, with an encoder that lets NaN and Infinity into the request."""
    headers = {**bench.ui(client), "Content-Type": "application/json"}
    return client.post(path, content=json.dumps(body), headers=headers)


def _effect(value):
    return lambda protocol: protocol["analysis"].update(target_effect=value)


SPOILED = {
    "nan effect": _effect(float("nan")),
    "infinite effect": _effect(float("inf")),
    "infinity as text": _effect("inf"),
    "nan factor": lambda protocol: protocol["treatments"][0]["factors"].update(light=float("nan")),
    "version zero": lambda protocol: protocol.update(version=0),
    "version beyond the limit": lambda protocol: protocol.update(version=10**30),
    "overlong id": lambda protocol: protocol.update(id="p" * 101),
}


def footprint(bench) -> tuple:
    """Everything the new routes could change, for 'nothing happened' assertions."""
    counts = [rows(bench, table) for table in TABLES]
    return (*counts, bench.workflow.round_state(bench.round_id), bench.state())


# --- project, protocol, round ------------------------------------------------------------------


def test_operator_creates_a_project_a_protocol_and_a_round(bench, operator):
    created = bench.post(operator, "/wb/projects", {"name": "lettuce light series"})
    assert created.status_code == 200
    project_id = created.json()["project_id"]

    saved = bench.post(operator, "/wb/protocols", {"protocol": protocol_json(project_id)})
    assert saved.status_code == 200
    expected = make_protocol(project_id=project_id, stages=("vegetative",))
    assert saved.json() == {"protocol_id": "protocol-1", "version": 1, "digest": expected.digest()}

    body = {"project_id": project_id, "protocol_id": "protocol-1"}
    made = bench.post(operator, "/wb/rounds", body)
    assert made.status_code == 200
    assert made.json()["state"] == "designing"
    assert bench.workflow.round_state(made.json()["round_id"]) is RoundState.DESIGNING


def test_round_overview_shows_the_state_and_the_stages(bench, operator):
    bench.pending()

    view = operator.get(f"/wb/rounds/{bench.round_id}")

    assert view.status_code == 200
    body = view.json()
    assert body["round_id"] == bench.round_id and body["project_id"] == bench.project_id
    assert (body["protocol_id"], body["protocol_version"]) == ("protocol-1", 1)
    assert body["state"] == "stage_review" and body["awaiting_choice"] is None
    assert (body["stages_done"], body["stage_total"]) == (0, 1)
    assert body["stages"] == [
        {"stage_id": "stage-1", "state": "pending_review", "stage_index": 1, "phase": "vegetative"}
    ]


def test_a_blank_project_name_is_refused(bench, operator):
    blank = bench.post(operator, "/wb/projects", {"name": "   "})
    missing = bench.post(operator, "/wb/projects", {})

    assert blank.status_code == 409 and detail(blank)["code"] == "state"
    assert missing.status_code == 422


def test_protocol_for_an_unknown_project_is_a_state_conflict(bench, operator):
    refused = bench.post(operator, "/wb/protocols", {"protocol": protocol_json("project-none")})

    assert refused.status_code == 409 and detail(refused)["code"] == "state"


def test_a_saved_protocol_version_cannot_be_overwritten(bench, operator):
    project_id, _round = designed(bench, operator)
    changed = protocol_json(project_id, hypothesis="something else")

    refused = bench.post(operator, "/wb/protocols", {"protocol": changed})
    bumped = bench.post(operator, "/wb/protocols", {"protocol": {**changed, "version": 2}})

    assert refused.status_code == 409 and "bump version" in detail(refused)["message"]
    assert bumped.status_code == 200 and bumped.json()["version"] == 2


def test_a_malformed_protocol_is_rejected(bench, operator):
    project_id = bench.post(operator, "/wb/projects", {"name": "series"}).json()["project_id"]
    broken = {**protocol_json(project_id), "approved": True}

    assert bench.post(operator, "/wb/protocols", {"protocol": broken}).status_code == 422
    assert bench.post(operator, "/wb/protocols", {"protocol": {"id": "p"}}).status_code == 422


@pytest.mark.parametrize("name", SPOILED)
def test_a_protocol_that_could_not_be_kept_faithfully_is_rejected(bench, operator, name):
    project_id = bench.post(operator, "/wb/projects", {"name": "series"}).json()["project_id"]
    protocol = protocol_json(project_id)
    SPOILED[name](protocol)

    refused = raw_post(bench, operator, "/wb/protocols", {"protocol": protocol})

    assert refused.status_code == 422 and detail(refused)["code"] == "param"
    assert rows(bench, "wf_protocols") == 0


def test_round_for_a_protocol_that_was_not_saved_is_a_state_conflict(bench, operator):
    project_id = bench.post(operator, "/wb/projects", {"name": "series"}).json()["project_id"]
    body = {"project_id": project_id, "protocol_id": "protocol-1"}

    refused = bench.post(operator, "/wb/rounds", body)

    assert refused.status_code == 409 and detail(refused)["code"] == "state"


def test_an_unknown_round_is_a_state_conflict(bench, operator):
    assert operator.get("/wb/rounds/round-none").status_code == 409
    assert bench.post(operator, "/wb/rounds/round-none/abort").status_code == 409
    assert (
        bench.post(operator, "/wb/rounds/round-none/choice", {"choice": "redo"}).status_code == 409
    )


def test_an_overlong_id_in_the_path_is_rejected(bench, operator):
    long_id = "x" * 101

    assert operator.get(f"/wb/rounds/{long_id}").status_code == 422
    assert operator.get(f"/wb/stages/{long_id}/run-sheet").status_code == 422
    assert bench.post(operator, f"/wb/rounds/{long_id}/abort").status_code == 422
    assert (
        bench.post(operator, f"/wb/rounds/{long_id}/choice", {"choice": "redo"}).status_code == 422
    )
    assert set_budget(bench, operator, long_id).status_code == 422


# --- call budget -------------------------------------------------------------------------------


def test_operator_sets_the_call_budget_of_a_project(bench, operator):
    project_id, _round = designed(bench, operator)

    answer = set_budget(bench, operator, project_id)

    assert answer.status_code == 200
    assert answer.json() == {
        "project_id": project_id,
        "max_calls": 50,
        "max_cost": 100.0,
        "remaining_calls": 50,
        "remaining_cost": 100.0,
    }
    assert bench.budget.remaining(project_id) == (50, 100.0)


def test_setting_a_budget_again_keeps_the_usage_already_recorded(bench, operator):
    project_id, _round = designed(bench, operator)
    set_budget(bench, operator, project_id, calls=10)
    bench.budget.reserve(project_id, 4)

    answer = set_budget(bench, operator, project_id, calls=20)

    assert answer.json()["remaining_calls"] == 16


def test_setting_a_budget_needs_a_recent_reauthentication(bench, operator):
    project_id, _round = designed(bench, operator)
    bench.clock.advance(301)

    stale = set_budget(bench, operator, project_id)

    assert stale.status_code == 403 and detail(stale)["code"] == "reauth_required"
    with pytest.raises(Denied):
        bench.budget.remaining(project_id)
    assert bench.post(operator, "/wb/reauth", {"secret": SECRET}).status_code == 200
    assert set_budget(bench, operator, project_id).status_code == 200


def test_budget_for_an_unknown_project_is_a_state_conflict(bench, operator):
    refused = set_budget(bench, operator, "project-none")

    assert refused.status_code == 409 and detail(refused)["code"] == "state"
    assert rows(bench, "call_budget") == 0


@pytest.mark.parametrize(
    "body",
    [
        {"max_calls": -1, "max_cost": 1.0},
        {"max_calls": 1, "max_cost": -0.5},
        {"max_calls": 1.5, "max_cost": 1.0},
        {"max_calls": "many", "max_cost": 1.0},
        {"max_calls": 1},
    ],
)
def test_a_malformed_budget_is_rejected(bench, operator, body):
    project_id, _round = designed(bench, operator)

    refused = bench.post(operator, f"/wb/projects/{project_id}/budget", body)

    assert refused.status_code == 422 and rows(bench, "call_budget") == 0


# --- research goal -----------------------------------------------------------------------------


def test_a_goal_creates_the_first_orchestrator_task(bench, operator):
    project_id, round_id = funded(bench, operator)
    body = {
        "project_id": project_id,
        "round_id": round_id,
        "goal": GOAL,
        "constraints": ["no pump"],
    }

    answer = bench.post(operator, "/wb/goals", body)

    assert answer.status_code == 200
    (task,) = bench.tasks.list(project_id)
    assert answer.json() == {"task_id": task.id, "state": "in_progress", "reused": False}
    assert (task.owner_role, task.question) == ("orchestrator", GOAL)
    assert task.state is TaskState.IN_PROGRESS
    assert task.constraints == ("no pump",) and task.input_refs == (f"round:{round_id}",)
    assert "alice" in task.trigger_event_id  # who asked is part of the trigger
    assert bench.tasks.open_tasks(["orchestrator"]) == (task,)


def test_a_goal_task_is_owned_and_budgeted_like_a_task_the_orchestrator_creates(bench, operator):
    project_id, _round = funded(bench, operator)

    bench.post(operator, "/wb/goals", {"project_id": project_id, "goal": GOAL})

    (task,) = bench.tasks.list(project_id)
    assert (task.owner_role, task.budget) == (ORCHESTRATOR, DEFAULT_TASK_BUDGET)


def test_a_goal_is_refused_until_the_project_has_a_budget(bench, operator):
    project_id, _round = designed(bench, operator)

    refused = bench.post(operator, "/wb/goals", {"project_id": project_id, "goal": GOAL})

    assert refused.status_code == 403 and detail(refused)["code"] == "budget"
    assert bench.tasks.list(project_id) == ()


@pytest.mark.parametrize(("calls", "cost"), [(0, 5.0), (5, 0.0)])
def test_a_goal_is_refused_when_the_budget_allows_no_model_call(bench, operator, calls, cost):
    project_id, _round = designed(bench, operator)
    assert set_budget(bench, operator, project_id, calls, cost).status_code == 200

    refused = bench.post(operator, "/wb/goals", {"project_id": project_id, "goal": GOAL})

    assert refused.status_code == 403 and detail(refused)["code"] == "budget"
    assert bench.tasks.list(project_id) == ()


def test_a_goal_is_refused_once_the_budget_is_used_up(bench, operator):
    project_id, _round = designed(bench, operator)
    set_budget(bench, operator, project_id, calls=1)
    bench.budget.reserve(project_id, 1)

    refused = bench.post(operator, "/wb/goals", {"project_id": project_id, "goal": GOAL})

    assert refused.status_code == 403 and detail(refused)["code"] == "budget"
    assert bench.tasks.list(project_id) == ()


def test_a_goal_for_an_unknown_project_is_a_state_conflict(bench, operator):
    refused = bench.post(operator, "/wb/goals", {"project_id": "project-none", "goal": GOAL})

    assert refused.status_code == 409 and detail(refused)["code"] == "state"


def test_a_goal_cannot_name_a_round_of_another_project(bench, operator):
    project_id, _round = funded(bench, operator)
    _other, foreign_round = designed(bench, operator, protocol_id="protocol-2")
    body = {"project_id": project_id, "round_id": foreign_round, "goal": GOAL}

    refused = bench.post(operator, "/wb/goals", body)

    assert refused.status_code == 409 and detail(refused)["code"] == "state"
    assert bench.tasks.list(project_id) == ()


@pytest.mark.parametrize("goal", ["", "   ", "x" * 2001])
def test_an_empty_or_oversized_goal_is_rejected(bench, operator, goal):
    project_id, _round = funded(bench, operator)

    refused = bench.post(operator, "/wb/goals", {"project_id": project_id, "goal": goal})

    assert refused.status_code == 422 and bench.tasks.list(project_id) == ()


def test_repeating_a_goal_with_the_same_request_id_creates_one_task(bench, operator):
    project_id, _round = funded(bench, operator)
    body = {"project_id": project_id, "goal": GOAL, "request_id": "goal-0001"}

    first = bench.post(operator, "/wb/goals", body).json()
    again = bench.post(operator, "/wb/goals", body).json()

    assert again == {**first, "reused": True}
    assert len(bench.tasks.list(project_id)) == 1


def test_a_request_id_cannot_be_reused_for_another_goal(bench, operator):
    project_id, _round = funded(bench, operator)
    body = {"project_id": project_id, "goal": GOAL, "request_id": "goal-0001"}
    assert bench.post(operator, "/wb/goals", body).status_code == 200

    refused = bench.post(operator, "/wb/goals", {**body, "goal": "something else"})

    assert refused.status_code == 409 and detail(refused)["code"] == "state"
    assert [task.question for task in bench.tasks.list(project_id)] == [GOAL]


def test_a_goal_goes_into_the_project_conversation_once(bench, operator):
    project_id, round_id = funded(bench, operator)
    body = {"project_id": project_id, "round_id": round_id, "goal": GOAL, "request_id": "goal-0001"}
    task_id = bench.post(operator, "/wb/goals", body).json()["task_id"]
    bench.post(operator, "/wb/goals", body)  # a repeat makes no second entry
    bench.conversation.add(project_id, "orchestrator", "reply", "on it", task_id)

    read = bench.lan.get(f"/wb/projects/{project_id}/conversation", headers=bench.ui(operator))

    assert read.status_code == 200
    first, second = read.json()["entries"]
    assert (first["role"], first["kind"], first["text"]) == ("user", "message", GOAL)
    assert first["task_id"] == task_id
    assert first["detail"] == {"operator": "alice", "round_id": round_id}
    assert (second["role"], second["text"]) == ("orchestrator", "on it")
    after = f"/wb/projects/{project_id}/conversation?after={first['seq']}"
    assert [
        e["text"] for e in bench.lan.get(after, headers=bench.ui(operator)).json()["entries"]
    ] == ["on it"]


def test_the_conversation_needs_an_operator_and_a_known_project(bench, operator):
    project_id, _round = funded(bench, operator)
    path = f"/wb/projects/{project_id}/conversation"

    assert bench.lan.get(path, headers=bench.model()).status_code == 403
    unknown = bench.lan.get("/wb/projects/project-none/conversation", headers=bench.ui(operator))
    assert unknown.status_code == 409 and detail(unknown)["code"] == "state"


@pytest.mark.parametrize("change", ["round_id", "constraints"])
def test_a_request_id_cannot_be_reused_with_another_round_or_other_constraints(
    bench, operator, change
):
    project_id, round_id = funded(bench, operator)
    body = {"project_id": project_id, "goal": GOAL, "request_id": "goal-0001"}
    assert bench.post(operator, "/wb/goals", body).status_code == 200
    changed = {"round_id": round_id, "constraints": ["no pump"]}[change]

    refused = bench.post(operator, "/wb/goals", {**body, change: changed})

    assert refused.status_code == 409 and detail(refused)["code"] == "state"
    (task,) = bench.tasks.list(project_id)
    assert (task.input_refs, task.constraints) == ((), ())


def test_goals_without_a_request_id_are_separate_tasks(bench, operator):
    project_id, _round = funded(bench, operator)
    body = {"project_id": project_id, "goal": GOAL}

    first = bench.post(operator, "/wb/goals", body).json()
    second = bench.post(operator, "/wb/goals", body).json()

    assert first["task_id"] != second["task_id"] and second["reused"] is False


def test_only_the_budget_waits_for_a_reauthentication(bench, operator):
    project_id, round_id = funded(bench, operator)
    bench.clock.advance(3600 * 6)  # the session is still alive, the reauthentication is old

    assert bench.post(operator, "/wb/projects", {"name": "later"}).status_code == 200
    goal = bench.post(operator, "/wb/goals", {"project_id": project_id, "goal": GOAL})
    assert goal.status_code == 200
    assert operator.get(f"/wb/rounds/{round_id}").status_code == 200


# --- run sheet review --------------------------------------------------------------------------


def test_operator_reads_the_run_sheet_and_its_findings_before_approving(bench, operator):
    bench.pending()
    note = Finding(code="evidence_missing", message="no evidence card", blocking=False)
    bench.workflow.validate = lambda _sheet: [note]
    sheet = bench.sheet()

    read = operator.get("/wb/stages/stage-1/run-sheet")

    assert read.status_code == 200
    body = read.json()
    assert body["stage_id"] == "stage-1" and body["state"] == "pending_review"
    assert body["run_sheet"] == sheet.model_dump(mode="json")
    assert (body["run_sheet_version"], body["run_sheet_digest"]) == (1, sheet.digest())
    # the validator's findings first, then the evidence hints (every set point here cites nothing)
    assert body["findings"][0] == note.model_dump(mode="json") and body["blocking"] is False
    assert {item["code"] for item in body["findings"][1:]} == {"no_evidence"}
    approval = bench.approve(operator).json()
    assert approval["run_sheet_digest"] == body["run_sheet_digest"]


def test_run_sheet_read_says_when_a_finding_blocks_the_approval(bench, operator):
    bench.pending()
    bench.workflow.validate = lambda _sheet: [Finding(code="capability", message="no such level")]

    body = operator.get("/wb/stages/stage-1/run-sheet").json()
    refused = bench.approve(operator)

    assert body["blocking"] is True and body["findings"][0]["code"] == "capability"
    assert refused.status_code == 403 and detail(refused)["code"] == "approval_invalid"


def test_reading_a_run_sheet_changes_nothing(bench, operator):
    bench.pending()
    assert bench.approve(operator).status_code == 200
    bench.workflow.validate = lambda _sheet: [Finding(code="capability", message="changed")]

    assert operator.get("/wb/stages/stage-1/run-sheet").json()["blocking"] is True

    assert bench.workflow.store.valid_approval("stage-1") is not None  # a read never voids
    assert bench.state() == "pending_review"


def test_run_sheet_of_an_unknown_stage_is_a_state_conflict(bench, operator):
    refused = operator.get("/wb/stages/stage-none/run-sheet")

    assert refused.status_code == 409 and detail(refused)["code"] == "state"


# --- after a stopped stage ---------------------------------------------------------------------


def test_a_stopped_stage_leaves_the_round_waiting_for_a_choice(bench, operator):
    stopped(bench, operator)

    assert round_view(bench, operator)["awaiting_choice"] == "stage-1"
    assert draft(bench, operator, "stage-2").status_code == 409


def test_redo_reopens_the_round_for_a_new_run_sheet(bench, operator):
    stopped(bench, operator)

    answer = choose(bench, operator, "redo")

    assert answer.status_code == 200
    assert answer.json() == {"round_id": bench.round_id, "state": "stage_review"}
    view = round_view(bench, operator)
    assert view["awaiting_choice"] is None and view["stages_done"] == 0
    assert draft(bench, operator, "stage-2").status_code == 200


def test_verify_moves_the_round_to_data_verification(bench, operator):
    stopped(bench, operator)

    assert choose(bench, operator, "verify").json()["state"] == "data_verification"


def test_next_is_refused_when_the_protocol_has_no_stage_left(bench, operator):
    stopped(bench, operator)

    refused = choose(bench, operator, "next")

    assert refused.status_code == 409 and detail(refused)["code"] == "state"
    assert round_view(bench, operator)["awaiting_choice"] == "stage-1"


def test_next_moves_on_to_the_following_stage_of_the_protocol(bench, operator):
    bench.project_id = bench.workflow.create_project("two stages", bench.designer)
    protocol = make_protocol(project_id=bench.project_id, stages=("vegetative", "flowering"))
    bench.workflow.save_protocol(protocol, bench.designer)
    bench.round_id = bench.workflow.create_round(bench.project_id, protocol.id, bench.designer)
    stopped(bench, operator)

    answer = choose(bench, operator, "next")

    assert answer.json()["state"] == "stage_review"
    assert round_view(bench, operator)["stages_done"] == 1


def test_choosing_abort_aborts_the_round(bench, operator):
    stopped(bench, operator)

    assert choose(bench, operator, "abort").json()["state"] == "aborted"
    assert bench.workflow.round_state(bench.round_id) is RoundState.ABORTED


def test_a_choice_without_a_stopped_stage_is_a_state_conflict(bench, operator):
    bench.pending()

    refused = choose(bench, operator, "redo")

    assert refused.status_code == 409 and detail(refused)["code"] == "state"


def test_an_unknown_choice_is_rejected(bench, operator):
    stopped(bench, operator)

    assert choose(bench, operator, "restart").status_code == 422
    assert round_view(bench, operator)["awaiting_choice"] == "stage-1"


# --- abort -------------------------------------------------------------------------------------


def test_operator_aborts_a_round_and_the_live_stage_gives_up_its_rights(bench, operator):
    running(bench, operator)

    answer = bench.post(operator, f"/wb/rounds/{bench.round_id}/abort")

    assert answer.status_code == 200
    assert answer.json() == {"round_id": bench.round_id, "state": "aborted"}
    stage = bench.workflow.stage("stage-1")
    assert stage.state.value == "stopped"
    assert (stage.right_number, stage.care_right, stage.manual_right) == (None, None, None)
    assert [reason for _number, reason in bench.control.handovers] == ["round aborted"] * 2


def test_a_round_can_be_aborted_before_it_has_a_stage(bench, operator):
    _project, round_id = designed(bench, operator)

    answer = bench.post(operator, f"/wb/rounds/{round_id}/abort")

    assert answer.json() == {"round_id": round_id, "state": "aborted"}


def test_aborting_twice_is_a_state_conflict(bench, operator):
    bench.pending()
    assert bench.post(operator, f"/wb/rounds/{bench.round_id}/abort").status_code == 200

    again = bench.post(operator, f"/wb/rounds/{bench.round_id}/abort")

    assert again.status_code == 409 and detail(again)["code"] == "state"


def test_choice_and_abort_never_wait_for_a_reauthentication(bench, operator):
    stopped(bench, operator)
    bench.clock.advance(3600 * 6)  # the session is still alive, the reauthentication is old

    assert choose(bench, operator, "redo").status_code == 200
    assert bench.post(operator, f"/wb/rounds/{bench.round_id}/abort").status_code == 200


# --- who may call ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ROUTES)
def test_model_token_cannot_call_any_round_endpoint(bench, name):
    bench.pending()
    before = footprint(bench)

    response = send(bench, bench.lan, name, headers=bench.model())

    assert response.status_code == 403 and detail(response)["code"] == "model_role"
    assert footprint(bench) == before


def test_identity_fields_in_a_goal_body_do_not_promote_a_model(bench):
    bench.pending()
    bench.budget.set(bench.project_id, Budget(max_calls=5, max_cost=1.0))
    body = {
        "project_id": bench.project_id,
        "goal": GOAL,
        "operator": "alice",
        "actor": {"kind": "operator", "id": "alice"},
    }

    response = bench.post(bench.lan, "/wb/goals", body, headers=bench.model("analyst"))

    assert response.status_code == 403 and detail(response)["code"] == "model_role"
    assert bench.tasks.list(bench.project_id) == ()


@pytest.mark.parametrize("name", ROUTES)
def test_round_endpoints_need_a_session(bench, name):
    bench.pending()
    before = footprint(bench)

    response = send(bench, bench.lan, name)

    assert response.status_code == 401 and detail(response)["code"] == "session"
    assert footprint(bench) == before


@pytest.mark.parametrize("name", WRITES)
def test_round_writes_need_the_workbench_origin_and_header(bench, operator, name):
    bench.pending()
    before = footprint(bench)

    no_header = send(bench, operator, name, ui=False)
    foreign = send(bench, operator, name, headers={"Origin": "http://evil.test"})

    for response in (no_header, foreign):
        assert response.status_code == 403 and detail(response)["code"] == "entry"
    assert footprint(bench) == before


@pytest.mark.parametrize("name", ROUTES)
def test_a_session_of_the_other_entry_is_refused(bench, operator, name):
    bench.pending()
    before = footprint(bench)
    bench.overlay.cookies.set(COOKIE, operator.cookies.get(COOKIE))

    response = send(bench, bench.overlay, name)

    assert response.status_code == 403 and detail(response)["code"] == "entry"
    assert footprint(bench) == before


def test_goal_and_budget_routes_are_absent_without_a_task_board_and_a_budget(bench):
    args = (bench.workflow, bench.control, bench.archive, bench.operators, bench.settings)
    app = create_app(
        bench.settings, bridge=object(), workbench=create_workbench(*args, ROLE_TOKENS)
    )
    bare = TestClient(app, base_url=f"http://{LAN_HOST}:{LAN_PORT}")
    assert bench.login(bare).status_code == 200
    project_id = bench.post(bare, "/wb/projects", {"name": "series"}).json()["project_id"]

    assert (
        bench.post(bare, "/wb/goals", {"project_id": project_id, "goal": GOAL}).status_code == 404
    )
    assert set_budget(bench, bare, project_id).status_code == 404


# --- the round's report --------------------------------------------------------------------------


def _published(bench, body: dict, kind: str = "research_report"):
    from growbridge.archive.ids import file_digest
    from growbridge.archive.models import Artifact

    round_id = bench.seed_round()
    path = bench.archive.root.parent / "agent_work" / "reports" / "report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")
    artifact = Artifact(
        id="artifact-1",
        task_id="task-1",
        kind=kind,
        path=str(path),
        sha256=file_digest(path),
        label="descriptive",
    )
    bench.archive.add_artifact(artifact)
    bench.workflow.store.update_round(round_id, report_artifact_id=artifact.id)
    return round_id, path


def test_the_report_of_a_round_is_read_from_its_verified_file(bench, operator):
    report = {"label": "descriptive", "conclusion": "uncertain", "limitations": ["one round"]}
    round_id, _ = _published(bench, report)

    body = operator.get(f"/wb/rounds/{round_id}/report").json()

    assert body["artifact_id"] == "artifact-1" and body["label"] == "descriptive"
    assert body["report"] == report


def test_a_report_file_changed_after_publishing_is_refused(bench, operator):
    round_id, path = _published(bench, {"conclusion": "uncertain"})
    path.write_text(json.dumps({"conclusion": "supported"}), encoding="utf-8")

    response = operator.get(f"/wb/rounds/{round_id}/report")

    assert response.status_code == 409 and "digest" in response.text


def test_a_round_without_a_report_has_none_to_read(bench, operator):
    round_id = bench.seed_round()

    response = operator.get(f"/wb/rounds/{round_id}/report")

    assert response.status_code == 409 and "no published report" in response.text


def test_the_report_read_names_the_primary_endpoint(bench, operator):
    round_id, _ = _published(bench, {"label": "descriptive"})

    body = operator.get(f"/wb/rounds/{round_id}/report").json()

    assert body["primary_endpoint"] == "canopy_area_growth"


def test_a_report_whose_protocol_is_gone_has_no_primary_endpoint(bench, operator):
    round_id, _ = _published(bench, {"label": "descriptive"})
    bench.workflow.store.db.execute("DELETE FROM wf_protocols")  # test database only

    body = operator.get(f"/wb/rounds/{round_id}/report").json()

    assert body["primary_endpoint"] is None


def _goal_language(bench, operator, project_id: str, **fields):
    answer = bench.post(operator, "/wb/goals", {"project_id": project_id, "goal": GOAL, **fields})
    return answer, bench.tasks.list(project_id)


def test_a_goal_stores_the_console_language_and_defaults_to_chinese(bench, operator):
    project_id, _round = funded(bench, operator)

    _answer, (asked,) = _goal_language(bench, operator, project_id, language="en")
    _answer, (_, plain) = _goal_language(bench, operator, project_id)

    assert (asked.language, plain.language) == ("en", "zh")


def test_a_resent_goal_in_another_language_returns_the_first_task(bench, operator):
    project_id, _round = funded(bench, operator)
    first, _tasks = _goal_language(
        bench, operator, project_id, request_id="goal-0001", language="en"
    )

    again, tasks = _goal_language(
        bench, operator, project_id, request_id="goal-0001", language="zh"
    )

    assert again.status_code == 200 and again.json()["reused"] is True
    assert again.json()["task_id"] == first.json()["task_id"]
    assert [t.language for t in tasks] == ["en"]


def test_an_unknown_language_is_refused(bench, operator):
    project_id, _round = funded(bench, operator)

    refused, tasks = _goal_language(bench, operator, project_id, language="fr")

    assert refused.status_code == 422 and tasks == ()
