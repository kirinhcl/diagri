"""Local alert rules and the durable alert book (architecture doc sections 8.1 and 8.3).

Threshold rules measure "for N seconds" on the monotonic clock and only ever look at a fresh, valid
reading. When the data is missing, stale or invalid, the rule loses its continuity and the sensor
is reported as a ``data_gap`` instead; an old reading never keeps an alert running or raises one.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol

from pydantic import Field

from growbridge.archive.clock import Clock
from growbridge.archive.db import Database
from growbridge.archive.ids import new_id
from growbridge.archive.models import Condition, Model
from growbridge.codes import checked
from growbridge.ports import Actor, Denied, Reading

Severity = Literal["info", "warning", "critical"]
DEFAULT_MAX_AGE_SECONDS = 120.0
REASK_SECONDS = 24 * 3600.0  # a persistent alert read earlier is asked about again after this
NAMESPACE = "observer_alerts"
STEPS = (
    "CREATE TABLE observer_alerts("
    "event_id TEXT PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL, severity TEXT NOT NULL, "
    "message TEXT NOT NULL, count INTEGER NOT NULL, first_at REAL NOT NULL, "
    "last_at REAL NOT NULL, resolved_at REAL, read_by TEXT, read_at REAL)",
    "CREATE INDEX observer_alerts_open ON observer_alerts(kind, key, resolved_at)",
    # The severity an operator read; NULL for a read recorded before this column existed.
    "ALTER TABLE observer_alerts ADD COLUMN read_severity TEXT",
    # The stable message code and its params (JSON); NULL for an alert stored before codes.
    "ALTER TABLE observer_alerts ADD COLUMN code TEXT",
    "ALTER TABLE observer_alerts ADD COLUMN params TEXT",
)
SEVERITY_ORDER: tuple[Severity, ...] = ("info", "warning", "critical")  # mildest first


class AlertHook(Protocol):
    """The hook a component raises alerts through (``Runtime._alert``); True when stored."""

    def __call__(
        self,
        kind: str,
        key: str,
        message: str,
        severity: Severity = ...,
        *,
        code: str | None = None,
        params: Mapping[str, object] | None = None,
    ) -> bool: ...


class AlertRule(Model):
    name: str
    sensor: str
    condition: Condition
    duration_seconds: float
    severity: Severity = "warning"
    pause_stage: bool = False
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS


class RuleState(Model):
    since_mono: float | None = None  # the condition has held without interruption since then
    active: bool = False  # the alert for this rule is currently raised


class AlertEvaluation(Model):
    states: dict[str, RuleState]
    fired: tuple[AlertRule, ...] = ()
    cleared: tuple[str, ...] = ()  # rule names
    data_gaps: tuple[str, ...] = ()  # sensors without usable data


def _fresh(rule: AlertRule, readings: Sequence[Reading], now_mono: float) -> float | None:
    """The newest reading's value if it is usable for a threshold decision."""
    matching = [r for r in readings if r.sensor == rule.sensor]
    if not matching:
        return None
    latest = max(matching, key=lambda r: r.mono)
    if latest.value is None or latest.quality != "ok":
        return None
    if now_mono - latest.mono > rule.max_age_seconds:
        return None
    return latest.value


def _step(
    rule: AlertRule, value: float, state: RuleState, now_mono: float
) -> tuple[RuleState, bool, bool]:
    """Returns (new state, fired, cleared) for one rule with usable data."""
    if not rule.condition.holds(value):
        return RuleState(), False, state.active
    since = state.since_mono if state.since_mono is not None else now_mono
    ripe = now_mono - since >= rule.duration_seconds
    fired = ripe and not state.active
    return RuleState(since_mono=since, active=state.active or ripe), fired, False


def evaluate_alert_rules(
    rules: Sequence[AlertRule],
    readings: Sequence[Reading],
    states: Mapping[str, RuleState],
    now_mono: float,
) -> AlertEvaluation:
    new_states: dict[str, RuleState] = {}
    fired: list[AlertRule] = []
    cleared: list[str] = []
    gaps: list[str] = []
    for rule in rules:
        state = states.get(rule.name, RuleState())
        value = _fresh(rule, readings, now_mono)
        if value is None:
            new_states[rule.name] = state.model_copy(update={"since_mono": None})
            if rule.sensor not in gaps:
                gaps.append(rule.sensor)
            continue
        new_states[rule.name], did_fire, did_clear = _step(rule, value, state, now_mono)
        if did_fire:
            fired.append(rule)
        if did_clear:
            cleared.append(rule.name)
    return AlertEvaluation(
        states=new_states, fired=tuple(fired), cleared=tuple(cleared), data_gaps=tuple(gaps)
    )


class Alert(Model):
    event_id: str
    kind: str
    key: str
    severity: Severity
    message: str
    count: int
    first_at: float
    last_at: float
    resolved_at: float | None = None
    read_by: str | None = None
    read_at: float | None = None
    read_severity: Severity | None = None
    code: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


def _alert(row) -> Alert:
    values = {name: row[name] for name in Alert.model_fields}
    values["params"] = json.loads(values["params"]) if values["params"] else {}
    return Alert(**values)


def _rank(severity: Severity) -> int:
    return SEVERITY_ORDER.index(severity)


def awaits_reading(alert: Alert, now: float, trusted: bool) -> bool:
    """An alert waits for an operator until it is read, again once it gets worse than the severity
    it was read at, and again once a day by the clock (``now``) however it was raised since. It
    fails closed on time: with a clock that is not trusted (``trusted`` False), or one that is
    behind the reading or the last raise, the alert waits. A read recorded without its severity
    (before that was kept) waits once more."""
    if alert.read_at is None or alert.read_severity is None:
        return True
    if _rank(alert.severity) > _rank(alert.read_severity):
        return True
    if not trusted or now < max(alert.read_at, alert.last_at):
        return True
    return now - alert.read_at > REASK_SECONDS


class AlertBook:
    def __init__(self, db: Database, clock: Clock):
        self.db = db
        self.clock = clock
        db.migrate(NAMESPACE, STEPS)

    def raise_alert(
        self,
        kind: str,
        key: str,
        severity: Severity,
        message: str,
        *,
        code: str | None = None,
        params: Mapping[str, object] | None = None,
    ) -> Alert:
        """Merge into the open event of the same kind and key, or start a new one. Without a code
        the alert is stored under its kind and no params."""
        now = self.clock.now()
        if code is None:
            code, stored = kind, {}
        else:
            stored = checked("alert", code, params or {})
        params_json = json.dumps(stored, sort_keys=True)
        with self.db.transaction():
            row = self.db.one(
                "SELECT event_id, read_severity FROM observer_alerts "
                "WHERE kind = ? AND key = ? AND resolved_at IS NULL",
                (kind, key),
            )
            if row is None:
                event_id = new_id("alert")
                self.db.execute(
                    "INSERT INTO observer_alerts(event_id, kind, key, severity, message, "
                    "count, first_at, last_at, code, params) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
                    (event_id, kind, key, severity, message, now, now, code, params_json),
                )
            else:
                event_id = row["event_id"]
                read_severity = row["read_severity"]
                if read_severity is not None and _rank(severity) < _rank(read_severity):
                    read_severity = severity  # re-arm: a later rise waits for a reader again
                self.db.execute(
                    "UPDATE observer_alerts SET count = count + 1, last_at = ?, "
                    "message = ?, severity = ?, read_severity = ?, code = ?, params = ? "
                    "WHERE event_id = ?",
                    (now, message, severity, read_severity, code, params_json, event_id),
                )
        return self.get(event_id)

    def get(self, event_id: str) -> Alert:
        row = self.db.one("SELECT * FROM observer_alerts WHERE event_id = ?", (event_id,))
        if row is None:
            raise Denied("state", f"unknown alert {event_id}")
        return _alert(row)

    def resolve(self, kind: str, key: str) -> bool:
        cursor = self.db.execute(
            "UPDATE observer_alerts SET resolved_at = ? "
            "WHERE kind = ? AND key = ? AND resolved_at IS NULL",
            (self.clock.now(), kind, key),
        )
        return cursor.rowcount > 0

    def open(self) -> tuple[Alert, ...]:
        rows = self.db.query(
            "SELECT * FROM observer_alerts WHERE resolved_at IS NULL ORDER BY first_at, event_id"
        )
        return tuple(_alert(row) for row in rows)

    def mark_read(self, event_id: str, actor: Actor) -> None:
        if actor.kind != "operator":
            raise Denied("not_operator", "only an operator can mark an alert as read")
        with self.db.transaction():  # the severity read is the one stored at this moment
            current = self.get(event_id)
            self.db.execute(
                "UPDATE observer_alerts SET read_by = ?, read_at = ?, read_severity = ? "
                "WHERE event_id = ?",
                (actor.id, self.clock.now(), current.severity, event_id),
            )
