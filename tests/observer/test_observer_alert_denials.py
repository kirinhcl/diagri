"""The refusals of the alert book carry a registered reason and params."""

import pytest

from growbridge.observer.alerts import AlertBook
from growbridge.ports import Actor, Denied


def test_record_not_found_carries_the_alert_kind_and_id(db, clock):
    with pytest.raises(Denied) as exc:
        AlertBook(db, clock).get("nope")
    assert exc.value.code == "state" and exc.value.reason == "record_not_found"
    assert exc.value.params == {"record_kind": "alert", "record_id": "nope"}


def test_not_operator_carries_no_params_for_an_alert_read_by_another_identity(db, clock):
    book = AlertBook(db, clock)
    alert = book.raise_alert("data_gap", "temperature", "warning", "no data")
    with pytest.raises(Denied) as exc:
        book.mark_read(alert.event_id, Actor(kind="model", id="x"))
    assert exc.value.code == "not_operator" and exc.value.reason == "not_operator"
    assert exc.value.params == {}
