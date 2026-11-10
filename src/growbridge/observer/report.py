"""Daily growth report: template-rendered numbers, optional model narrative (section 8.1)."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from growbridge.archive.db import Database
from growbridge.archive.models import Model
from growbridge.observer.metrics import DailyMetrics

NAMESPACE = "observer_reports"
STEPS = (
    "CREATE TABLE observer_reports("
    "project_id TEXT NOT NULL, report_date TEXT NOT NULL, text TEXT NOT NULL, "
    "PRIMARY KEY(project_id, report_date))",
)
GAP_LIST_LIMIT = 5
MAX_CATCH_UP_DAYS = 7


class ReportContext(Model):
    project_id: str
    project_name: str
    protective_actions: tuple[str, ...] = ()
    manual_interventions: tuple[str, ...] = ()
    observations: tuple[str, ...] = ()  # manual crop observations until cameras exist
    todos: tuple[str, ...] = ()
    treatment_deviation: float | None = None  # fraction of time the actual treatment deviated


def _clock(seconds: float) -> str:
    return f"{int(seconds) // 3600:02d}:{int(seconds) % 3600 // 60:02d}"


def _section(title: str, items: tuple[str, ...]) -> list[str]:
    return [f"{title}:"] + [f"- {item}" for item in items] if items else [f"{title}: none"]


def _environment(metrics: DailyMetrics) -> list[str]:
    lines = ["Environment (time-weighted):"]
    for key, mean in sorted(metrics.means.items()):
        outside = metrics.out_of_range_seconds.get(key)
        suffix = f", out of range {outside / 60:.1f} min" if outside is not None else ""
        lines.append(f"- {key}: mean {mean:.2f}{suffix}")
    if metrics.dli is not None:
        lines.append(f"- DLI: {metrics.dli:.2f} mol/m2/d")
    return lines


def _coverage(metrics: DailyMetrics) -> list[str]:
    lines = [f"Data coverage: {metrics.coverage * 100:.1f}%"]
    for gap in metrics.gaps[:GAP_LIST_LIMIT]:
        lines.append(f"- gap {_clock(gap.start_offset)}-{_clock(gap.end_offset)}")
    if len(metrics.gaps) > GAP_LIST_LIMIT:
        lines.append(f"- and {len(metrics.gaps) - GAP_LIST_LIMIT} more gaps")
    return lines


def render_daily_report(
    metrics: DailyMetrics, context: ReportContext, narrative: str | None = None
) -> str:
    """Every figure comes from ``metrics``; the narrative is appended verbatim and labelled."""
    deviation = context.treatment_deviation
    lines = [f"Daily report {metrics.date} - {context.project_name}", ""]
    lines += _environment(metrics) + [""] + _coverage(metrics) + [""]
    if deviation is not None:
        lines += [f"Treatment deviation: {deviation * 100:.1f}%", ""]
    lines += _section("Protective actions", context.protective_actions) + [""]
    lines += _section("Manual interventions", context.manual_interventions) + [""]
    lines += _section("Crop observations", context.observations) + [""]
    lines += _section("To do", context.todos)
    if narrative:
        lines += ["", "Narrative (model-written, no new figures):", narrative]
    return "\n".join(lines)


def reports_due(
    now: float,
    report_time: str,
    timezone: str,
    last_date: str | None,
    max_days: int = MAX_CATCH_UP_DAYS,
) -> tuple[str, ...]:
    """Every local date still to report, oldest first, up to yesterday and once ``report_time``
    has passed. After downtime the missed days follow ``last_date``; at most the ``max_days``
    most recent ones are returned. Without history only yesterday is due."""
    local = datetime.fromtimestamp(now, ZoneInfo(timezone))
    hours, minutes = (int(part) for part in report_time.split(":"))
    if (local.hour, local.minute) < (hours, minutes):
        return ()
    yesterday = local.date() - timedelta(days=1)
    first = date.fromisoformat(last_date) + timedelta(days=1) if last_date else yesterday
    first = max(first, yesterday - timedelta(days=max_days - 1))
    count = (yesterday - first).days + 1
    return tuple((first + timedelta(days=i)).isoformat() for i in range(max(count, 0)))


def report_due(now: float, report_time: str, timezone: str, last_date: str | None) -> str | None:
    """The oldest local date still to report, or ``None`` (see ``reports_due``)."""
    days = reports_due(now, report_time, timezone, last_date)
    return days[0] if days else None


class ReportStore:
    def __init__(self, db: Database):
        self.db = db
        db.migrate(NAMESPACE, STEPS)

    def save(self, project_id: str, report_date: str, text: str) -> bool:
        """Idempotent per project and date: the first report of a day stays."""
        cursor = self.db.execute(
            "INSERT OR IGNORE INTO observer_reports(project_id, report_date, text) "
            "VALUES (?, ?, ?)",
            (project_id, report_date, text),
        )
        return cursor.rowcount == 1

    def get(self, project_id: str, report_date: str) -> str | None:
        row = self.db.one(
            "SELECT text FROM observer_reports WHERE project_id = ? AND report_date = ?",
            (project_id, report_date),
        )
        return row["text"] if row else None
