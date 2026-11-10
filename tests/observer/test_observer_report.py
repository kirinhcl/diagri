from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from growbridge.observer.metrics import compute_daily_metrics
from growbridge.observer.report import (
    ReportContext,
    ReportStore,
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
