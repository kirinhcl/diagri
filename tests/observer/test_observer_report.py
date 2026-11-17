from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from growbridge.observer.metrics import compute_daily_metrics
from growbridge.observer.report import (
    FROZEN_LIST_LIMIT,
    ReportContext,
    ReportStore,
    frozen_line,
    frozen_lines,
    render_daily_report,
    report_due,
    reports_due,
)

TZ = "Europe/Helsinki"


def local(year, month, day, hour, minute=0, zone=TZ) -> float:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(zone)).timestamp()


@pytest.fixture
def metrics(make_sample):
    samples = [make_sample(t, {"temperature": 31.25}) for t in range(0, 3600, 60)]
    return compute_daily_metrics(
        samples, date(2026, 11, 10), TZ, 120.0, {"temperature": (20.0, 28.0)}
    )


def test_report_numbers_come_from_metrics_without_a_model(metrics):
    context = ReportContext(project_id="p1", project_name="Basil run 3")

    text = render_daily_report(metrics, context)

    assert "2026-11-10" in text and "Basil run 3" in text
    assert "31.25" in text
    assert f"{metrics.coverage * 100:.1f}" in text


def test_report_lists_context_items_and_narrative(metrics):
    context = ReportContext(
        project_id="p1",
        project_name="Basil",
        protective_actions=("fan to 10 at 14:02",),
        manual_interventions=("operator opened tent",),
        observations=("leaf curl on plant 3",),
        todos=("measure height",),
        treatment_deviation=0.02,
    )

    text = render_daily_report(metrics, context, narrative="Stable day overall.")

    for item in ("fan to 10 at 14:02", "operator opened tent", "leaf curl", "measure height"):
        assert item in text
    assert "Stable day overall." in text
    assert "2.0" in text


def test_report_lists_frozen_readings(metrics):
    item = "temp stuck at 24 from 08:00 to 10:05"
    listed = ReportContext(project_id="p1", project_name="Basil", frozen_readings=(item,))
    empty = ReportContext(project_id="p1", project_name="Basil")

    assert "Frozen readings:" in render_daily_report(metrics, listed)
    assert f"- {item}" in render_daily_report(metrics, listed)
    assert "Frozen readings: none" in render_daily_report(metrics, empty)


DAY = (local(2026, 11, 10, 0), local(2026, 11, 11, 0))


def test_frozen_line_with_an_unformattable_time_says_unknown_time():
    period = {"sensor": "temp", "value": 24.0, "first_at": 1e20, "last_at": None}

    assert frozen_line(period, TZ, *DAY) == "temp stuck at 24 from unknown time (still frozen)"


def test_a_period_closed_for_another_reason_than_a_change_says_it_is_no_longer_checked():
    base = {"sensor": "temp", "value": 24.0, "first_at": DAY[0] + 3600, "last_at": DAY[0] + 7200}

    changed = frozen_line({**base, "close_reason": "value_changed"}, TZ, *DAY)
    dropped = frozen_line({**base, "close_reason": "no_longer_listed"}, TZ, *DAY)
    nothing = frozen_line({**base, "close_reason": "nothing_checked"}, TZ, *DAY)

    assert changed == "temp stuck at 24 from 01:00 to 02:00"
    assert dropped == "temp stuck at 24 from 01:00 to 02:00 (no longer checked)"
    assert nothing == dropped


def test_a_closed_period_without_a_recorded_reason_is_not_shown_as_a_recovery():
    base = {"sensor": "temp", "value": 24.0, "first_at": DAY[0] + 3600, "last_at": DAY[0] + 7200}

    assert frozen_line({**base, "close_reason": None}, TZ, *DAY) == (
        "temp stuck at 24 from 01:00 to 02:00 (close reason unrecorded)"
    )
    assert frozen_line(base, TZ, *DAY).endswith("(close reason unrecorded)")


def test_report_still_renders_when_one_frozen_time_is_absurd(metrics):
    bad = {"sensor": "temp", "value": 24.0, "first_at": 1e20, "last_at": 1e20}
    good = {"sensor": "humi", "value": 55.0, "first_at": DAY[0] + 3600, "last_at": None}
    lines = tuple(frozen_line(p, TZ, *DAY) for p in (bad, good))
    context = ReportContext(project_id="p1", project_name="Basil", frozen_readings=lines)

    text = render_daily_report(metrics, context)

    assert "- temp stuck at 24 from unknown time to unknown time" in text
    assert "- humi stuck at 55 from 01:00 (still frozen)" in text


def test_the_cap_keeps_open_periods_first_and_names_the_dropped_sensors(metrics):
    closed = [
        {"sensor": n, "value": 1.0, "first_at": DAY[0] + 600 * i, "last_at": DAY[0] + 600 * i + 60}
        for i, n in enumerate(["temp", "co2", "temp", "humi", "tempSoil", "co2", "temp"])
    ]
    open_late = {"sensor": "vent", "value": 2.0, "first_at": DAY[0] + 9000, "last_at": None}
    lines = frozen_lines([*closed, open_late], TZ, *DAY)

    assert len(lines) == FROZEN_LIST_LIMIT + 1
    assert lines[0].startswith("vent stuck at 2") and "(still frozen)" in lines[0]
    assert lines[1].startswith("temp stuck at 1 from 00:00")
    assert lines[-1] == "and 3 more (tempSoil, co2, temp)"
    context = ReportContext(project_id="p1", project_name="Basil", frozen_readings=lines)
    assert f"- {lines[-1]}" in render_daily_report(metrics, context).splitlines()


def test_an_unusable_timestamp_is_logged(caplog):
    period = {
        "period_id": "frozen-1",
        "sensor": "t",
        "value": 1.0,
        "first_at": 1e20,
        "last_at": None,
    }

    with caplog.at_level("WARNING"):
        frozen_line(period, TZ, *DAY)

    assert "frozen period frozen-1 has an unusable timestamp" in caplog.text


def test_narrative_is_appended_and_template_numbers_stay(metrics):
    context = ReportContext(project_id="p1", project_name="Basil")

    text = render_daily_report(metrics, context, narrative="Mean was 99.9 C.")

    assert "31.25" in text


def test_report_due_uses_project_timezone():
    now = local(2026, 11, 11, 7, 30)

    assert report_due(now, "07:00", TZ, None) == "2026-11-10"
    assert report_due(now, "09:00", TZ, None) is None


def test_report_date_is_the_local_yesterday_not_the_utc_one():
    # 00:30 local on 11-11 is 22:30 UTC on 11-10: the local day just ended is 11-10
    now = local(2026, 11, 11, 0, 30)

    assert report_due(now, "00:10", TZ, None) == "2026-11-10"
    assert report_due(now, "00:10", "UTC", None) == "2026-11-09"


def test_report_due_not_repeated_for_the_same_day():
    now = local(2026, 11, 11, 8)

    assert report_due(now, "07:00", TZ, "2026-11-10") is None
    assert report_due(now, "07:00", TZ, "2026-11-09") == "2026-11-10"


def test_reports_due_lists_every_missed_day_oldest_first():
    now = local(2026, 11, 11, 8)

    assert reports_due(now, "07:00", TZ, "2026-11-07") == ("2026-11-08", "2026-11-09", "2026-11-10")
    assert reports_due(now, "07:00", TZ, "2026-11-09") == ("2026-11-10",)
    assert reports_due(now, "07:00", TZ, "2026-11-10") == ()
    assert reports_due(local(2026, 11, 11, 6), "07:00", TZ, "2026-11-08") == ()  # not yet 07:00


def test_reports_due_is_capped_to_the_most_recent_days():
    now = local(2026, 11, 20, 8)

    days = reports_due(now, "07:00", TZ, "2026-10-01", max_days=3)

    assert days == ("2026-11-17", "2026-11-18", "2026-11-19")
    assert len(reports_due(now, "07:00", TZ, "2026-10-01")) == 7


def test_reports_due_without_history_reports_only_yesterday():
    assert reports_due(local(2026, 11, 11, 8), "07:00", TZ, None) == ("2026-11-10",)


def test_report_due_returns_the_oldest_missing_date():
    now = local(2026, 11, 11, 8)

    assert report_due(now, "07:00", TZ, "2026-11-07") == "2026-11-08"
    assert report_due(now, "07:00", TZ, "2026-11-10") is None


def test_report_store_saves_one_report_per_project_and_day(db):
    store = ReportStore(db)

    assert store.save("p1", "2026-11-10", "first") is True
    assert store.save("p1", "2026-11-10", "second") is False
    assert store.save("p2", "2026-11-10", "other project") is True
    assert store.get("p1", "2026-11-10") == "first"
    assert store.get("p1", "2026-11-11") is None


def test_report_lists_recurring_patterns(metrics):
    lines = (
        "protect:hot on 4 of the last 7 days, around 14:05",
        "co2 frozen on 3 of the last 7 days, around 02:00",
    )
    context = ReportContext(project_id="p", project_name="Basil", recurring=lines)

    text = render_daily_report(metrics, context)
    assert "Recurring:\n- protect:hot on 4 of the last 7 days, around 14:05\n- co2 frozen" in text


def test_report_without_recurring_has_no_section(metrics):
    text = render_daily_report(metrics, ReportContext(project_id="p", project_name="Basil"))

    assert "Recurring" not in text
