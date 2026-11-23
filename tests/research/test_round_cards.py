"""A delivered round's report conclusion becomes a verified, project-scoped local card."""

import json
import sys
from pathlib import Path

import pytest

from growbridge.agents.memory_rounds import load_report, report_snapshots
from growbridge.archive.evidence_book import card_statuses
from growbridge.planning.evidence_validity import evidence_gate
from growbridge.ports import Denied
from growbridge.research.round_cards import RoundCardInput, convert_round, round_card_refusal
from growbridge.sim.fixtures import make_protocol, make_run_sheet
from growbridge.vocab import packaged_catalog
from growbridge.workflow.states import RoundState

PROJECT = "p-a"
CATALOG = packaged_catalog()
NOTHING = RoundCardInput()


@pytest.fixture
def world(tmp_path):
    sys.path.insert(0, str(Path(__file__).parents[1] / "agents"))
    from test_memory_rounds import World  # one way to build rounds and reports

    built = World(tmp_path)
    built.store.put_protocol(
        make_protocol(id="proto", project_id=PROJECT, cultivar="Butterhead"), 0
    )
    return built


def refusal(call) -> tuple[str, dict]:
    with pytest.raises(Denied) as caught:
        call()
    return caught.value.reason, caught.value.params


def convert(world, round_id="r1", body=NOTHING):
    return convert_round(world.src(), CATALOG, round_id, body, "alice")


def test_a_delivered_round_becomes_a_verified_local_card(world):
    snap = world.snapshot("snap-a", "exp-r1")
    world.round("r1", chain=(f"snapshot:{snap}",))

    card = convert(world)

    (entry,) = world.archive.evidence_entries()
    assert entry.card.id == card.id and entry.verified_by == "alice"
    assert entry.source == "operator:alice"
    assert card.source_class == "local" and card.calibrated
    assert card.claim == "supported" and card.variable == "canopy_area_growth"
    assert card.crop_taxon == "NCBITaxon:4236" and card.cultivar == "Butterhead"
    origin = world.archive.ledger.origin(card.id)
    assert origin.label == "confirmatory" and origin.round_id == "r1"
    assert origin.project_id == PROJECT and origin.report_artifact_id == "art-r1"
    assert origin.snapshot_ids == (snap,)


def test_a_long_conclusion_is_cut_to_the_claim_limit(world):
    world.round("r1", conclusion="x" * 1500)

    card = convert(world)

    assert len(card.claim) == 1000 and card.claim.endswith("…")


def test_a_held_out_report_is_refused(world):
    world.round("r1", holdout_id="h1")

    assert refusal(lambda: convert(world)) == (
        "round_card_report_unusable",
        {"round_id": "r1", "problem": "held_out"},
    )


def test_an_invalid_report_is_refused(world):
    snap = world.snapshot("snap-a", "exp-r1")
    world.round("r1", chain=(f"snapshot:{snap}",))
    world.archive.mark_dependents_invalid("rec-snap-a")

    assert refusal(lambda: convert(world))[1]["problem"] == "invalid"


def test_a_changed_report_file_is_refused_as_unavailable(world):
    world.round("r1")
    (world.tmp / "report-r1.json").write_text(json.dumps({"conclusion": "other"}))

    assert refusal(lambda: convert(world))[1]["problem"] == "unavailable"


def test_a_delivered_round_without_a_report_is_refused_as_unavailable(world):
    world.round("r1")
    world.store.update_round("r1", report_artifact_id=None)

    assert refusal(lambda: convert(world)) == (
        "round_card_report_unusable",
        {"round_id": "r1", "problem": "unavailable"},
    )


def test_an_unfinished_round_is_refused(world):
    world.round("r1", state=RoundState.STAGE_RUNNING)

    assert refusal(lambda: convert(world)) == (
        "round_card_not_delivered",
        {"round_id": "r1", "state": "stage_running"},
    )


def test_a_report_converts_once(world):
    world.round("r1")
    first = convert(world)

    reason, params = refusal(lambda: convert(world))

    assert (reason, params) == ("round_card_exists", {"round_id": "r1", "card_id": first.id})
    assert len(world.archive.evidence_entries()) == 1


@pytest.mark.parametrize("conclusion", [..., "", "  ", 123])
def test_a_report_without_a_conclusion_is_refused(world, conclusion):
    world.round("r1", conclusion=conclusion)

    assert refusal(lambda: convert(world)) == ("round_card_no_conclusion", {"round_id": "r1"})
    assert world.archive.evidence_entries() == ()


def test_the_pre_click_refusal_matches_what_converting_says(world):
    world.round("ok")
    world.round("bad", conclusion="")

    assert round_card_refusal(world.src(), "ok") is None
    assert round_card_refusal(world.src(), "bad") == (
        "round_card_no_conclusion",
        {"round_id": "bad"},
    )
    convert(world, "ok")
    reason, params = round_card_refusal(world.src(), "ok")
    assert reason == "round_card_exists" and params["round_id"] == "ok" and params["card_id"]


def test_a_value_takes_the_catalog_unit_of_the_endpoint_when_none_is_given(world):
    world.round("r1")

    card = convert(world, body=RoundCardInput(value=0.4))

    assert card.value == 0.4 and card.unit == "cm2/d"


def test_a_wrong_unit_is_refused_and_nothing_is_written(world):
    world.round("r1")

    reason, _ = refusal(lambda: convert(world, body=RoundCardInput(value=0.4, unit="kg")))

    assert reason == "evidence_card_invalid"
    assert world.archive.evidence_entries() == ()
    assert world.archive.ledger.origins() == {}
    assert convert(world).claim == "supported"


def test_a_card_without_a_value_has_no_unit(world):
    world.round("r1")

    assert convert(world).unit is None


def test_an_endpoint_outside_the_catalog_gives_a_card_without_a_variable(world):
    world.store.put_protocol(
        make_protocol(id="proto", project_id=PROJECT, version=2).model_copy(
            update={
                "analysis": make_protocol().analysis.model_copy(
                    update={"primary_endpoint": "tempB"}
                )
            }
        ),
        0,
    )
    world.round("r1")
    world.store.update_round("r1", protocol_version=2)

    card = convert(world, body=RoundCardInput(value=1.0, unit="x"))

    assert card.variable is None and card.unit == "x"


def test_marking_the_snapshot_invalid_blocks_the_card(world):
    snap = world.snapshot("snap-a", "exp-r1")
    world.round("r1", chain=(f"snapshot:{snap}",))
    card = convert(world)
    assert card_statuses(world.archive, [card.id], PROJECT)[card.id].validity == "active"

    world.archive.mark_dependents_invalid("rec-snap-a")

    status = card_statuses(world.archive, [card.id], PROJECT)[card.id]
    assert status.validity == "dependency_invalid" and status.invalid_dependency == snap
    sheet = make_run_sheet(project_id=PROJECT)
    cited = tuple(a.model_copy(update={"evidence": card.id}) for a in sheet.timed_actions[:1])
    findings = evidence_gate(sheet.model_copy(update={"timed_actions": cited}), world.archive)
    assert [f.code for f in findings] == ["dependency_invalid_source"]


def test_report_snapshots_lists_the_artifact_snapshot_then_the_chain_without_repeats(world):
    first = world.snapshot("snap-a", "exp-r1")
    second = world.snapshot("snap-b", "exp-r1")
    world.round("r1", snapshot=first, chain=(f"snapshot:{second}", f"snapshot:{first}", "x"))
    artifact = world.archive.artifact("art-r1")
    body = json.loads((world.tmp / "report-r1.json").read_text())

    assert report_snapshots(world.src(), PROJECT, artifact, body) == (first, second)


def test_the_memory_downgrade_still_holds(world):
    snap = world.snapshot("snap-a", "exp-r1")
    world.round("r1", snapshot=snap)
    world.archive.mark_dependents_invalid("rec-snap-a")

    downgrade, body = load_report(world.src(), PROJECT, "art-r1")

    assert downgrade == {"invalid": True, "label": "confirmatory"} and body is None
