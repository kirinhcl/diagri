import pytest

from growbridge.archive.models import Condition
from growbridge.observer.alerts import (
    NAMESPACE,
    STEPS,
    AlertBook,
    AlertRule,
    RuleState,
    awaits_reading,
    evaluate_alert_rules,
)
from growbridge.ports import Actor, Denied, Reading

HOT = AlertRule(
    name="too_hot",
    sensor="temperature",
    condition=Condition(op=">", value=30.0),
    duration_seconds=60.0,
    severity="critical",
    pause_stage=True,
)


def reading(value, mono, quality="ok", sensor="temperature"):
    return Reading(
        sensor=sensor, value=value, unit="C", at=1.8e9 + mono, mono=mono, quality=quality
    )


def evaluate(readings, states, now, rules=(HOT,)):
    return evaluate_alert_rules(rules, readings, states, now)


def test_rule_fires_only_after_the_duration_and_only_once():
    first = evaluate([reading(31, 1000)], {}, 1000)
    assert first.fired == ()
    assert first.states["too_hot"].since_mono == 1000

    second = evaluate([reading(31, 1060)], first.states, 1060)
    assert [r.name for r in second.fired] == ["too_hot"]

    third = evaluate([reading(31, 1070)], second.states, 1070)
    assert third.fired == ()
    assert third.states["too_hot"].active is True


def test_rule_clears_when_the_condition_stops_holding():
    fired = evaluate([reading(31, 1060)], {"too_hot": RuleState(since_mono=1000)}, 1060)

    cleared = evaluate([reading(25, 1070)], fired.states, 1070)

    assert cleared.cleared == ("too_hot",)
    assert cleared.states["too_hot"] == RuleState()


def test_stale_reading_is_a_data_gap_and_does_not_fire_or_count_time():
    states = {"too_hot": RuleState(since_mono=1000)}

    result = evaluate([reading(35, 1010)], states, 1500)

    assert result.fired == ()
    assert result.data_gaps == ("temperature",)
    assert result.states["too_hot"].since_mono is None


def test_missing_none_and_invalid_readings_are_data_gaps():
    for readings in ([], [reading(None, 1000)], [reading(35, 1000, quality="invalid")]):
        result = evaluate(readings, {}, 1000)
        assert result.data_gaps == ("temperature",)
        assert result.fired == ()


def test_gap_keeps_an_active_alert_active_and_not_resolved():
    states = {"too_hot": RuleState(since_mono=1000, active=True)}

    result = evaluate([], states, 2000)

    assert result.cleared == ()
    assert result.states["too_hot"].active is True
    assert result.states["too_hot"].since_mono is None


def test_wall_clock_is_not_used():
    # the reading's wall time is absurd; only mono matters
    odd = Reading(sensor="temperature", value=31, unit="C", at=0.0, mono=1000.0)

    result = evaluate([odd], {}, 1000)

    assert result.states["too_hot"].since_mono == 1000


def test_book_merges_the_same_event_and_counts(db, clock):
    book = AlertBook(db, clock)

    first = book.raise_alert("threshold", "too_hot", "critical", "31 C")
    clock.advance(30)
    second = book.raise_alert("threshold", "too_hot", "critical", "32 C")

    assert second.event_id == first.event_id
    assert second.count == 2
    assert second.last_at > second.first_at
    assert len(book.open()) == 1


def test_book_resolve_then_raise_starts_a_new_event(db, clock):
    book = AlertBook(db, clock)
    first = book.raise_alert("threshold", "too_hot", "critical", "31 C")

    assert book.resolve("threshold", "too_hot") is True
    assert book.open() == ()
    assert book.resolve("threshold", "too_hot") is False
    again = book.raise_alert("threshold", "too_hot", "critical", "33 C")

    assert again.event_id != first.event_id
    assert again.count == 1


def test_only_an_operator_may_mark_an_alert_read(db, clock):
    book = AlertBook(db, clock)
    alert = book.raise_alert("data_gap", "temperature", "warning", "no data")

    for kind in ("model", "workflow", "observer", "probe"):
        with pytest.raises(Denied) as denied:
            book.mark_read(alert.event_id, Actor(kind=kind, id="x"))
        assert denied.value.code == "not_operator"
    assert book.open()[0].read_by is None

    book.mark_read(alert.event_id, Actor(kind="operator", id="alice"))

    assert book.open()[0].read_by == "alice"


def test_mark_read_keeps_the_severity_it_was_read_at(db, clock):
    book = AlertBook(db, clock)
    alert = book.raise_alert("data_gap", "temperature", "warning", "no data")

    book.mark_read(alert.event_id, Actor(kind="operator", id="alice"))

    assert book.get(alert.event_id).read_severity == "warning"


@pytest.mark.parametrize(
    ("read_at", "now", "waiting"),
    [
        ("warning", "warning", False),  # raised again at the same severity: still read
        ("warning", "info", False),  # milder: still read
        ("warning", "critical", True),  # worse: waits again
        ("info", "warning", True),
    ],
)
def test_a_read_alert_waits_again_only_when_it_gets_worse(db, clock, read_at, now, waiting):
    book = AlertBook(db, clock)
    alert = book.raise_alert("data_gap", "temperature", read_at, "no data")
    book.mark_read(alert.event_id, Actor(kind="operator", id="alice"))
    clock.advance(30)

    again = book.raise_alert("data_gap", "temperature", now, "still no data")

    assert awaits_reading(again) is waiting


def test_an_unread_alert_waits_and_one_read_before_severity_was_kept_waits_again(db, clock):
    book = AlertBook(db, clock)
    alert = book.raise_alert("data_gap", "temperature", "warning", "no data")
    assert awaits_reading(alert) is True
    legacy = alert.model_copy(update={"read_by": "alice", "read_at": alert.last_at})

    assert awaits_reading(legacy) is True  # no severity kept at reading: ask once more


def test_an_older_alert_table_gains_the_column_and_keeps_its_rows(db, clock):
    db.migrate(NAMESPACE, STEPS[:2])  # the table as it was before read_severity
    db.execute(
        "INSERT INTO observer_alerts(event_id, kind, key, severity, message, count, first_at, "
        "last_at, read_by, read_at) VALUES ('a1', 'data_gap', 't', 'warning', 'm', 3, 1, 2, "
        "'alice', 2)"
    )

    alert = AlertBook(db, clock).get("a1")

    assert (alert.read_by, alert.read_at, alert.count, alert.read_severity) == ("alice", 2, 3, None)


def test_mark_read_of_unknown_event_is_denied(db, clock):
    with pytest.raises(Denied) as denied:
        AlertBook(db, clock).mark_read("nope", Actor(kind="operator", id="alice"))
    assert denied.value.code == "state"


def test_alerts_survive_a_new_book_on_the_same_database(db, clock):
    AlertBook(db, clock).raise_alert("data_gap", "temperature", "warning", "no data")

    assert len(AlertBook(db, clock).open()) == 1
