from vocab_support import LOOP_ENTRIES

from growbridge.archive.evidence_ledger import EvidenceOrigin, EvidenceRelation
from growbridge.archive.evidence_status import CardStatus, Replacement
from growbridge.archive.models import CareRule, Channel, EvidenceCard, TimedAction
from growbridge.planning.evidence_validity import (
    check_evidence_fit,
    check_evidence_validity,
    cited_card_ids,
    evidence_gate,
    evidence_hints,
    stale_evidence_lines,
)
from growbridge.sim.fixtures import humidity_rule, make_run_sheet
from growbridge.vocab import load_catalog, packaged_catalog, packaged_text

CATALOG = packaged_catalog()
TAXON = "NCBITaxon:4236"
OTHER_TAXON = "NCBITaxon:3562"
RULE = {"source_kind": "feedback_rule", "source": "humidity-exhaust"}


def card(card_id="H", **fields):
    base = {"id": card_id, "source_class": "paper", "citation": "Doe 2020", "claim": "c"}
    return EvidenceCard(**{**base, **fields})


def sheet_citing(ref, rule=False, care=False, **rule_fields):
    """A run sheet where the first timed action, or one rule, or one care step cites ``ref``."""
    base = make_run_sheet()
    if rule:
        return base.model_copy(
            update={"feedback_rules": (humidity_rule(evidence=ref, **rule_fields),)}
        )
    if care:
        step = TimedAction(id="s1", at="01:00", channel=Channel.LIGHT, level=50, evidence=ref)
        return base.model_copy(
            update={"care_rules": (CareRule(id="care", channel=Channel.LIGHT, schedule=(step,)),)}
        )
    actions = tuple(a.model_copy(update={"evidence": ref}) for a in base.timed_actions[:1])
    return base.model_copy(update={"timed_actions": actions})


def only(findings):
    (found,) = findings
    return found


def test_cited_card_ids_drop_user_input_and_repeats_and_keep_order():
    base = make_run_sheet()
    actions = tuple(
        a.model_copy(update={"evidence": ref})
        for a, ref in zip(base.timed_actions, ("B", "user:note", "A"), strict=True)
    )
    sheet = base.model_copy(
        update={"timed_actions": actions, "feedback_rules": (humidity_rule(evidence="B"),)}
    )
    assert cited_card_ids(sheet) == ("B", "A")
    assert cited_card_ids(make_run_sheet()) == ()


def test_a_superseded_card_blocks_and_names_the_replacement():
    status = CardStatus(
        card_id="H",
        validity="superseded",
        superseded_by="P",
        current_replacement=Replacement(card_id="P", validity="active"),
    )
    f = only(check_evidence_validity(sheet_citing("H", rule=True), {"H": status}))
    assert (f.code, f.blocking) == ("superseded_source", True)
    assert f.params == {
        **RULE,
        "card_id": "H",
        "replacement_id": "P",
        "replacement_validity": "active",
    }


def test_a_superseded_card_without_a_replacement_card_has_none_params():
    status = CardStatus(card_id="H", validity="superseded", superseded_by="P")
    f = only(check_evidence_validity(sheet_citing("H", care=True), {"H": status}))
    assert f.params == {
        "source_kind": "care_step",
        "source": "care/s1",
        "card_id": "H",
        "replacement_id": None,
        "replacement_validity": None,
    }


def test_a_retracted_card_blocks_with_its_reason():
    status = CardStatus(card_id="H", validity="retracted", retracted_reason="wrong table")
    f = only(check_evidence_validity(sheet_citing("H", rule=True), {"H": status}))
    assert (f.code, f.blocking) == ("retracted_source", True)
    assert f.params == {**RULE, "card_id": "H", "reason": "wrong table"}


def test_a_dependency_invalid_card_blocks_and_names_the_invalid_dependency():
    status = CardStatus(card_id="H", validity="dependency_invalid", invalid_dependency="snap-1")
    f = only(check_evidence_validity(sheet_citing("H", rule=True), {"H": status}))
    assert (f.code, f.blocking) == ("dependency_invalid_source", True)
    assert f.params == {**RULE, "card_id": "H", "dependency_id": "snap-1"}


def test_user_input_and_active_cards_never_block():
    assert check_evidence_validity(sheet_citing("user:note"), {}) == ()
    assert check_evidence_validity(sheet_citing("H"), {"H": CardStatus(card_id="H")}) == ()
    assert check_evidence_validity(sheet_citing("ghost"), {}) == ()


def test_one_finding_per_citing_point():
    status = CardStatus(card_id="H", validity="retracted", retracted_reason="x")
    sheet = sheet_citing("H")
    both = sheet.model_copy(update={"feedback_rules": (humidity_rule(evidence="H"),)})
    assert len(check_evidence_validity(both, {"H": status})) == 2


def fit(sheet, cards, catalog=CATALOG, taxon="", origins=None, statuses=None):
    statuses = statuses or {c: CardStatus(card_id=c) for c in cards}
    return check_evidence_fit(sheet, cards, statuses, origins or {}, catalog, taxon)


def test_a_contested_card_gives_a_hint_with_the_others():
    status = CardStatus(card_id="H", contested_with=("X", "Y"))
    f = only(fit(sheet_citing("H"), {"H": card()}, statuses={"H": status}))
    assert (f.code, f.blocking) == ("contested_source", False)
    assert f.params == {
        "source_kind": "timed_action",
        "source": make_run_sheet().timed_actions[0].id,
        "card_id": "H",
        "others": "X,Y",
    }


def test_a_pending_relation_gives_a_hint_with_the_relations():
    status = CardStatus(card_id="H", pending=("r1", "r2"))
    f = only(fit(sheet_citing("H", rule=True), {"H": card()}, statuses={"H": status}))
    assert (f.code, f.blocking) == ("pending_relation", False)
    assert f.params == {**RULE, "card_id": "H", "relations": "r1,r2"}


def test_a_variable_mismatch_names_both_variables():
    c = card(variable="relative_humidity", value=70.0, unit="%")
    sheet = sheet_citing("H", rule=True, sensor="temp", unit="C")
    f = only(fit(sheet, {"H": c}))
    assert (f.code, f.blocking) == ("variable_mismatch", False)
    assert f.params == {
        **RULE,
        "card_id": "H",
        "rule_variable": "temp",
        "card_variable": "relative_humidity",
    }


def test_a_sensor_alias_matches_the_cards_variable():
    c = card(variable="air_temperature", value=25.0, unit="Cel")
    sheet = sheet_citing("H", rule=True, sensor="temp", unit="C")
    assert fit(sheet, {"H": c}) == ()


def test_a_sensor_outside_the_catalog_gives_no_variable_hint():
    c = card(variable="air_temperature", value=25.0, unit="Cel")
    sheet = sheet_citing("H", rule=True, sensor="tempB", unit="C")
    assert fit(sheet, {"H": c}) == ()


def test_a_sensor_outside_the_catalog_still_gets_the_unit_check():
    c = card(variable="air_temperature", value=77.0, unit="degF")
    sheet = sheet_citing("H", rule=True, sensor="tempB", unit="C")
    f = only(fit(sheet, {"H": c}))
    assert (f.code, f.blocking) == ("evidence_unit_mismatch", False)
    assert f.params == {**RULE, "card_id": "H", "rule_unit": "C", "card_unit": "degF"}


def test_a_unit_mismatch_names_both_units():
    c = card(variable="air_temperature", value=77.0, unit="degF")
    sheet = sheet_citing("H", rule=True, sensor="temp", unit="C")
    f = only(fit(sheet, {"H": c}))
    assert (f.code, f.blocking) == ("evidence_unit_mismatch", False)
    assert f.params == {**RULE, "card_id": "H", "rule_unit": "C", "card_unit": "degF"}


def test_an_old_card_gets_uncataloged_not_a_unit_hint():
    c = card(value=200.0, unit="umol m-2 s-1")
    f = only(fit(sheet_citing("H", rule=True), {"H": c}))
    assert (f.code, f.blocking) == ("uncataloged_card", False)
    assert f.params == {**RULE, "card_id": "H"}


def test_a_replacement_loop_in_the_catalog_gives_a_variable_mismatch():
    catalog = load_catalog(packaged_text() + LOOP_ENTRIES)
    c = card(variable="loop_a", value=1.0, unit="1")
    sheet = sheet_citing("H", rule=True, sensor="humi", unit="%")
    assert only(fit(sheet, {"H": c}, catalog)).code == "variable_mismatch"


def test_crop_mismatch_needs_both_taxa():
    c = card(crop_taxon=TAXON)
    sheet = sheet_citing("H")
    f = only(fit(sheet, {"H": c}, taxon=OTHER_TAXON))
    assert (f.code, f.blocking) == ("crop_mismatch", False)
    assert f.params == {
        "source_kind": "timed_action",
        "source": make_run_sheet().timed_actions[0].id,
        "card_id": "H",
        "card_taxon": TAXON,
        "protocol_taxon": OTHER_TAXON,
    }
    assert fit(sheet, {"H": c}, taxon="") == ()
    assert fit(sheet, {"H": card()}, taxon=OTHER_TAXON) == ()
    assert fit(sheet, {"H": c}, taxon=TAXON) == ()


def origin(label):
    return EvidenceOrigin(
        card_id="H",
        project_id="project-1",
        round_id="r",
        report_artifact_id="a",
        snapshot_ids=(),
        label=label,
        at=0.0,
    )


def test_a_descriptive_round_card_gets_exploratory_finding():
    sheet = sheet_citing("H", care=True)
    f = only(fit(sheet, {"H": card()}, origins={"H": origin("descriptive")}))
    assert (f.code, f.blocking) == ("exploratory_finding", False)
    assert f.params == {
        "source_kind": "care_step",
        "source": "care/s1",
        "card_id": "H",
        "label": "descriptive",
    }
    assert fit(sheet, {"H": card()}, origins={"H": origin("confirmatory")}) == ()


def test_user_input_and_unknown_cards_get_no_fit_hint():
    assert fit(sheet_citing("user:note"), {}) == ()
    assert fit(sheet_citing("ghost"), {}) == ()


def relation(rid, kind, subject, obj, at=1.0):
    return EvidenceRelation(
        id=rid,
        kind=kind,
        subject_id=subject,
        object_id=obj,
        reason="why",
        source="operator:op",
        task_id=None,
        project_id=None,
        proposed_in=None,
        at=at,
    )


def test_the_gate_reads_statuses_from_the_archive(archive):
    archive.add_evidence(card("H"))
    archive.add_evidence(card("P"))
    archive.ledger.add_relation(relation("r1", "supersedes", "P", "H"), confirmed_by="op")
    f = only(evidence_gate(sheet_citing("H"), archive))
    assert (f.code, f.params["replacement_id"]) == ("superseded_source", "P")


def test_the_hints_read_cards_and_origins_from_the_archive(archive):
    archive.add_evidence(card("H", crop_taxon=TAXON))
    found = evidence_hints(sheet_citing("H"), archive, CATALOG, OTHER_TAXON)
    assert [f.code for f in found] == ["crop_mismatch"]


def test_stale_lines_use_the_replacement_when_it_is_active(archive):
    archive.add_evidence(card("H"))
    archive.add_evidence(card("P"))
    archive.ledger.add_relation(relation("r1", "supersedes", "P", "H"), confirmed_by="op")
    (line,) = stale_evidence_lines(sheet_citing("H", rule=True), archive)
    assert line == "feedback rule humidity-exhaust: card H is superseded; use P"


def test_stale_lines_say_when_the_replacement_is_not_active(archive):
    for ident in ("H", "P"):
        archive.add_evidence(card(ident))
    archive.ledger.add_relation(relation("r1", "supersedes", "P", "H"), confirmed_by="op")
    archive.ledger.add_relation(relation("r2", "retracts", "P", None, at=2.0), confirmed_by="op")
    (line,) = stale_evidence_lines(sheet_citing("H", rule=True), archive)
    assert (
        line == "feedback rule humidity-exhaust: card H is superseded; replacement P is retracted"
    )


def test_stale_lines_without_a_replacement_stop_at_the_validity(archive):
    archive.add_evidence(card("H"))
    archive.ledger.add_relation(relation("r1", "retracts", "H", None), confirmed_by="op")
    (line,) = stale_evidence_lines(sheet_citing("H", rule=True), archive)
    assert line == "feedback rule humidity-exhaust: card H is retracted"


def test_stale_lines_are_capped_at_five(archive):
    base = make_run_sheet()
    rules = tuple(humidity_rule(id=f"rule-{i}", evidence=f"H{i}") for i in range(7))
    for i in range(7):
        archive.add_evidence(card(f"H{i}"))
        archive.ledger.add_relation(relation(f"r{i}", "retracts", f"H{i}", None), confirmed_by="op")
    sheet = base.model_copy(update={"feedback_rules": rules})
    assert len(stale_evidence_lines(sheet, archive)) == 5
    assert len(stale_evidence_lines(sheet, archive, limit=2)) == 2
