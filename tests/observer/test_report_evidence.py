from datetime import date
from types import SimpleNamespace

from growbridge.observer.metrics import compute_daily_metrics
from growbridge.observer.report import ReportContext, render_daily_report
from growbridge.planning.evidence_validity import report_stale_evidence

TITLE = "Evidence no longer valid"


def render(**fields) -> str:
    metrics = compute_daily_metrics([], date(2026, 11, 10), "UTC", 120.0, {})
    context = ReportContext(project_id="p1", project_name="Basil", **fields)
    return render_daily_report(metrics, context)


def test_the_section_appears_only_when_there_are_lines():
    assert TITLE not in render(stale_evidence=())

    text = render(stale_evidence=("rule heat: card c1 is superseded; use c2",))

    assert f"{TITLE}:\n- rule heat: card c1 is superseded; use c2" in text
    assert text.index(TITLE) < text.index("To do:")


def test_a_failure_leaves_the_section_out():
    class Broken:
        def stage(self, stage_id):
            raise RuntimeError("disk")

    runtime = SimpleNamespace(workflow=Broken(), archive=None)

    assert report_stale_evidence(runtime, SimpleNamespace(stage_id="s1")) == ()


def test_no_running_stage_gives_no_lines():
    assert report_stale_evidence(SimpleNamespace(), None) == ()
