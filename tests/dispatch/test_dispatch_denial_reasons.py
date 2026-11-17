"""Tool refusals in the orchestrator, planner, evidence and researcher roles carry a reason and
params (the tool result a model reads is unchanged: see tests/agents)."""

from __future__ import annotations

from test_dispatch_evidence import CARD
from test_dispatch_orchestrator import HANDOFF, _register
from test_dispatch_report_frozen import FIELDS as FROZEN_FIELDS
from test_dispatch_report_frozen import VALUES as FROZEN_VALUES
from test_dispatch_report_frozen import _rounds as frozen_rounds
from test_dispatch_report_frozen import _runner, _save_v2
from test_dispatch_report_frozen import _snapshot as frozen_snapshot
from test_dispatch_researcher import PUBLISH_FIELDS, _rounds

from growbridge.agents import handlers_evidence, handlers_report
from growbridge.sim.fixtures import make_protocol
from growbridge.workflow.states import TaskState


async def _publish_refusal(env, task_id, rounds, deps=None, fields=None, **extra):
    fields = {"protocol_id": env.protocol.id, **(fields or PUBLISH_FIELDS), **extra}
    return await env.refusal(
        "researcher", "publish_research_report", deps, task_id=task_id, snapshots=rounds, **fields
    )


async def test_request_id_reused_for_other_goal_carries_the_owner_and_the_trigger(env):
    parent = env.task("orchestrator", "goal:p:dev:g-1", question="does light help?")
    fields = {k: v for k, v in HANDOFF.items() if k not in {"to_role", "goal"}}
    fields.update(to_role="planner", goal="design it", trigger_event_id=parent.trigger_event_id)

    exc = await env.refusal(
        "orchestrator", "delegate_task", bound=parent.id, project_id=env.project_id, **fields
    )

    assert (exc.code, exc.reason) == ("state", "request_id_reused_for_other_goal")
    assert exc.params == {"task_id": parent.id, "request_id": parent.trigger_event_id}


async def test_a_task_of_another_project_is_not_this_run(env):
    other, _ = env.other_project()
    foreign = env.task_in(other, "researcher", "ev-foreign")
    own = env.task("orchestrator", "ev-own")

    exc = await env.refusal("orchestrator", "get_task_status", bound=own.id, task_id=foreign.id)

    assert (exc.code, exc.reason, exc.params) == ("scope", "not_this_run", {})


async def test_artifact_digest_mismatch_does_not_know_the_round(env):
    env.work_root.mkdir(parents=True)
    path = env.work_root / "note.txt"
    path.write_text("original")
    _register(env, "art-4", path)
    path.write_text("tampered")

    exc = await env.refusal("orchestrator", "read_artifact", artifact_id="art-4")

    assert (exc.code, exc.reason) == ("state", "artifact_digest_mismatch")
    assert exc.params == {"round_id": None, "artifact_id": "art-4"}


async def test_an_artifact_outside_the_known_roots_is_not_this_run(env, tmp_path):
    outside = tmp_path / "elsewhere" / "secret.txt"
    outside.parent.mkdir()
    outside.write_text("token")
    _register(env, "art-3", outside)

    exc = await env.refusal("orchestrator", "read_artifact", artifact_id="art-3")

    assert (exc.code, exc.reason, exc.params) == ("scope", "not_this_run", {})


async def test_operator_only_evidence_has_no_params(env):
    task = env.task("planner")

    exc = await env.refusal(
        "planner", "propose_evidence_card", task_id=task.id, **{**CARD, "source_class": "local"}
    )

    assert (exc.code, exc.reason, exc.params) == ("param", "operator_only_evidence", {})


async def test_an_evidence_card_from_another_kind_of_task_is_refused(env):
    task = env.task("researcher")

    exc = await env.refusal("planner", "propose_evidence_card", task_id=task.id, **CARD)

    assert (exc.code, exc.reason, exc.params) == ("scope", "wrong_task_kind", {"task_kind": None})


async def test_quota_proposal_limit_carries_the_limit(env, monkeypatch):
    monkeypatch.setattr(handlers_evidence, "MAX_PROPOSALS_PER_TASK", 0)
    task = env.task("planner")

    exc = await env.refusal("planner", "propose_evidence_card", task_id=task.id, **CARD)

    assert (exc.code, exc.reason) == ("quota", "quota_proposal_limit")
    assert exc.params == {"max_proposals": 0}


async def test_a_protocol_the_planner_cannot_find_carries_protocol_and_project(env):
    exc = await env.refusal(
        "planner",
        "check_experimental_design",
        project_id=env.project_id,
        protocol_id="protocol-none",
    )

    assert (exc.code, exc.reason) == ("state", "protocol_not_found")
    assert exc.params == {"protocol_id": "protocol-none", "project_id": env.project_id}


async def test_publishing_for_an_unknown_protocol_carries_protocol_and_project(env):
    task = env.task("researcher")

    exc = await _publish_refusal(env, task.id, _rounds(env), protocol_id="protocol-none")

    assert (exc.code, exc.reason) == ("state", "protocol_not_found")
    assert exc.params == {"protocol_id": "protocol-none", "project_id": env.project_id}


async def test_task_not_in_progress_carries_the_state(env):
    task = env.task("researcher")
    env.tasks.transition(task.id, TaskState.NEEDS_ATTENTION, "e-1", "operator hold")

    exc = await _publish_refusal(env, task.id, _rounds(env))

    assert (exc.code, exc.reason) == ("state", "task_not_in_progress")
    assert exc.params == {"task_id": task.id, "status": "needs_attention"}


async def test_snapshot_invalidated_carries_the_snapshot(env):
    task = env.task("researcher")
    rounds = _rounds(env)
    env.archive.mark_dependents_invalid("m1")

    exc = await _publish_refusal(env, task.id, rounds)

    assert (exc.code, exc.reason) == ("state", "snapshot_invalidated")
    assert exc.params == {"snapshot_id": rounds[0]["snapshot_id"]}


async def test_snapshot_fails_verification_carries_the_snapshot(env):
    task = env.task("researcher")
    rounds = _rounds(env)
    path = env.archive.root / "snapshots" / rounds[0]["snapshot_id"] / "measurements.jsonl"
    path.write_text(path.read_text().replace("5.0", "50.0"))

    exc = await _publish_refusal(env, task.id, rounds)

    assert (exc.code, exc.reason) == ("snapshot_incomplete", "snapshot_fails_verification")
    assert exc.params == {"snapshot_id": rounds[0]["snapshot_id"]}


async def test_duplicate_experiment_carries_the_experiment(env):
    task = env.task("researcher")
    first = _rounds(env)[0]

    exc = await _publish_refusal(env, task.id, [first, {**first, "round": 2}])

    assert (exc.code, exc.reason) == ("param", "duplicate_experiment")
    assert exc.params == {"experiment_id": "e1"}


async def test_unknown_treatment_carries_the_treatment(env):
    task = env.task("researcher")

    exc = await _publish_refusal(env, task.id, _rounds(env), treatment_id="nope")

    assert (exc.code, exc.reason) == ("param", "unknown_treatment")
    assert exc.params == {"treatment_id": "nope"}


async def test_table_invalid_carries_the_detail(env, monkeypatch):
    def refuse(*args, **kwargs):
        raise ValueError("round 5 has no allocation")

    monkeypatch.setattr(handlers_report, "unit_table", refuse)
    task = env.task("researcher")

    exc = await _publish_refusal(env, task.id, _rounds(env))

    assert (exc.code, exc.reason) == ("param", "table_invalid")
    assert exc.params == {"detail": "round 5 has no allocation"}


async def test_snapshots_of_two_protocol_versions_are_a_mixed_protocol(env, tmp_path):
    task = env.task("researcher")
    first = frozen_snapshot(env, 1, FROZEN_VALUES[0])
    _save_v2(env)
    later = [frozen_snapshot(env, n, v, version=2) for n, v in enumerate(FROZEN_VALUES[1:], 2)]
    rounds = [{"snapshot_id": s, "round": n} for n, s in enumerate([first, *later], 1)]
    deps = env.make_deps(runner=_runner(env, tmp_path, freeze=False))

    exc = await _publish_refusal(env, task.id, rounds, deps, FROZEN_FIELDS)

    assert (exc.code, exc.reason, exc.params) == ("param", "snapshots_mixed_protocol", {})


async def test_snapshots_of_another_protocol_carry_the_protocol_named(env, tmp_path):
    task = env.task("researcher")
    deps = env.make_deps(runner=_runner(env, tmp_path, freeze=False))
    # the named protocol must exist to pass the precheck
    env.workflow.save_protocol(
        make_protocol(project_id=env.project_id, id="protocol-x"), env.operator
    )

    exc = await _publish_refusal(
        env, task.id, frozen_rounds(env), deps, FROZEN_FIELDS, protocol_id="protocol-x"
    )

    assert (exc.code, exc.reason) == ("param", "snapshots_other_protocol")
    assert exc.params == {"protocol_id": "protocol-x"}


async def test_confirmatory_run_pending_carries_the_first_unfinished_snapshot(env, tmp_path):
    task = env.task("researcher")
    rounds = frozen_rounds(env)
    deps = env.make_deps(runner=_runner(env, tmp_path))

    exc = await _publish_refusal(env, task.id, rounds, deps, FROZEN_FIELDS)

    assert (exc.code, exc.reason) == ("state", "confirmatory_run_pending")
    assert exc.params == {"snapshot_id": rounds[0]["snapshot_id"]}
