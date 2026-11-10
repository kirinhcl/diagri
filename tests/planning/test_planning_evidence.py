from growbridge.archive.models import CareRule, Channel, EvidenceCard, TimedAction
from growbridge.planning.validate import check_evidence
from growbridge.sim.fixtures import humidity_rule, make_run_sheet


def card(card_id="card-1", **fields):
    base = {
        "id": card_id,
        "source_class": "paper",
        "citation": "Doe 2020, Table 2",
        "claim": "lettuce grows well at 60 % light",
        "verified": True,
    }
    return EvidenceCard(**{**base, **fields})


def sheet_with_evidence(evidence):
    base = make_run_sheet()
    actions = tuple(a.model_copy(update={"evidence": evidence}) for a in base.timed_actions)
    return base.model_copy(update={"timed_actions": actions})


def codes(findings):
    return [f.code for f in findings]


def test_verified_calibrated_card_yields_no_findings():
    sheet = sheet_with_evidence("card-1")
    assert check_evidence(sheet, {"card-1": card()}) == ()


def test_missing_evidence_reference_is_no_evidence_and_not_blocking():
    findings = check_evidence(make_run_sheet(), {})
    assert set(codes(findings)) == {"no_evidence"}
    assert all(not f.blocking for f in findings)
    assert len(findings) == 3  # one per timed action


def test_reference_to_unknown_card_is_no_evidence():
    findings = check_evidence(sheet_with_evidence("ghost"), {})
    assert set(codes(findings)) == {"no_evidence"}


def test_user_input_reference_counts_as_evidence():
    assert check_evidence(sheet_with_evidence("user:operator-note"), {}) == ()


def test_unverified_online_source_needs_confirmation():
    findings = check_evidence(sheet_with_evidence("card-1"), {"card-1": card(verified=False)})
    assert set(codes(findings)) == {"unverified_source"}
    assert all(not f.blocking for f in findings)
    assert "card-1" in findings[0].message


def test_local_measurement_does_not_need_verification():
    local = card(source_class="local", verified=False)
    assert check_evidence(sheet_with_evidence("card-1"), {"card-1": local}) == ()


def test_uncalibrated_card_is_flagged():
    findings = check_evidence(sheet_with_evidence("card-1"), {"card-1": card(calibrated=False)})
    assert set(codes(findings)) == {"uncalibrated"}
    assert "未校准" in findings[0].message


def test_unverified_and_uncalibrated_both_reported():
    both = card(verified=False, calibrated=False)
    findings = check_evidence(sheet_with_evidence("card-1"), {"card-1": both})
    assert {"unverified_source", "uncalibrated"} <= set(codes(findings))


def test_feedback_rule_and_care_steps_are_checked():
    step = TimedAction(id="care-1", channel=Channel.FAN, at="01:00", level=2)
    sheet = make_run_sheet(
        timed_actions=(),
        feedback_rules=(humidity_rule(),),
        care_rules=(CareRule(id="care", channel=Channel.FAN, schedule=(step,)),),
    )
    findings = check_evidence(sheet, {})
    assert len(findings) == 2
    assert any("humidity-exhaust" in f.message for f in findings)
    assert any("care-1" in f.message for f in findings)
