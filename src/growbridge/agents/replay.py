"""Replay a recorded model run against the current code (design spec §10, §11).

The recorded model replies are handed back in order (``ReplayClient``); a tool marked ``external``
returns its recorded result and its handler never runs; every other tool runs for real and its
result is compared with the recording after masking generated ids, the data directory and clock
jitter (``same_result``). The first step that differs stops the replay unless ``keep_going``.
``replay_trace`` reports every step, both ends and an exit code: 0 the same, 1 a mismatch,
2 cannot replay.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from growbridge.agents.dispatch import Dispatcher
from growbridge.agents.llm import ModelClient, ModelReply, ToolCall
from growbridge.agents.roles import ROLES
from growbridge.agents.run_end import RunEnd, RunInterrupted
from growbridge.agents.tools import ToolOutcome, Toolset, is_gate_refusal
from growbridge.agents.trace import Trace, sha256_json
from growbridge.agents.trace_show import INCOMPLETE
from growbridge.archive.models import Model, ResearchTask
from growbridge.config import RoleModel
from growbridge.ports import Denied
from growbridge.workflow.states import TaskState

ID_PATTERN = re.compile(r"\b([a-z][a-z0-9]*)_[0-9a-f]{32}\b")
DENIED_PATTERN = re.compile(r"^Error: denied \(([^)]*)\)")  # how Toolset words a refusal
TIMESTAMP_MIN = 1e9  # a JSON number above this is a time in epoch seconds
TIME_SLACK_SECONDS = 1.0  # allowed on top of the recorded tool's own duration
EXIT_SAME, EXIT_DIFFERENT, EXIT_CANNOT = 0, 1, 2
NO_LINE_LEFT = "no recorded tool call is left for this call"
NOT_CALLED = "recorded, but the replay did not make this call"
GATE_OPENED = (
    "the record was refused before the handler, but the tool's gate now lets this call "
    "through; the external handler was not run in the replay"
)


class ReplayClock:
    """Wall time stands where the record says (set before each step); monotonic time is real."""

    def __init__(self, start: float, synced: bool | None = True):
        self._now = float(start)
        self.synced = True if synced is None else synced

    def now(self) -> float:
        return self._now

    def monotonic(self) -> float:
        return time.monotonic()

    def set(self, at: float) -> None:
        self._now = float(at)


class ReplayedModelError(RuntimeError):
    """The recorded model call failed; the replay fails it the same way."""


class ReplayExhausted(RunInterrupted):
    """The replay asked for a model reply the record does not have."""


class ReplayStop(RunInterrupted):
    """A tool result differs from the record and the replay stops there."""


def _reply(line: Mapping[str, Any]) -> ModelReply:
    return ModelReply(
        stop_reason=line["stop_reason"],
        text=line.get("text", ""),
        tool_calls=tuple(ToolCall.model_validate(c) for c in line.get("tool_calls") or ()),
        content=line.get("content"),
        input_tokens=line.get("input_tokens", 0),
        output_tokens=line.get("output_tokens", 0),
    )


class ReplayClient:
    """Hands the recorded model replies back in order; a recorded error is raised again."""

    def __init__(self, models: Sequence[dict], clock: ReplayClock):
        self._models = tuple(models)
        self._clock = clock
        self._served = 0

    @property
    def served(self) -> int:
        """How many recorded model lines the replay has taken."""
        return self._served

    async def create(self, **request: Any) -> ModelReply:
        if self._served >= len(self._models):
            raise ReplayExhausted(
                f"the replay asked for more model replies than the {len(self._models)} recorded"
            )
        line = self._models[self._served]
        self._served += 1
        self._clock.set(line["at"])
        if "error" in line:
            raise ReplayedModelError(line["error"])
        return _reply(line)


class ReplayBudget:
    """Lets the recorded number of model calls through, then refuses as the record did (if it
    did); charges nothing."""

    def __init__(self, calls: int, refusal: Mapping[str, Any] | None):
        self._calls = calls
        self._refusal = refusal
        self._reserved = 0

    def reserve(self, project_id: str, calls: int = 1) -> None:
        self._reserved += calls
        refusal = self._refusal
        if self._reserved <= self._calls or refusal is None:
            return
        raise Denied(
            refusal["code"],
            refusal.get("message", ""),
            reason=refusal.get("reason"),
            params=refusal.get("params") or {},
        )

    def charge(self, project_id: str, cost: float) -> None:
        """A replay spends nothing."""


def mask_ids(text: str) -> str:
    return ID_PATTERN.sub(r"\1_*", text)


class IdMap:
    """Generated ids of the record, each paired with the id the replay made in its place."""

    def __init__(self) -> None:
        self._pairs: dict[str, str] = {}

    @property
    def pairs(self) -> dict[str, str]:
        return dict(self._pairs)

    def learn(self, recorded: str, replayed: str) -> None:
        """Pair the ids of two texts by position, only when both hold as many ids. A known id
        keeps its first pair; an id the replay kept, or one of another kind, makes no pair."""
        old = [m.group(0) for m in ID_PATTERN.finditer(recorded)]
        new = [m.group(0) for m in ID_PATTERN.finditer(replayed)]
        if len(old) != len(new):
            return
        for was, now in zip(old, new, strict=True):
            same_kind = was.rsplit("_", 1)[0] == now.rsplit("_", 1)[0]
            if was != now and same_kind and was not in self._pairs:
                self._pairs[was] = now

    def apply(self, value: Any) -> Any:
        """A new copy of ``value`` with every known recorded id replaced (keys and strings)."""
        if isinstance(value, str):
            return ID_PATTERN.sub(self._swap, value)
        if isinstance(value, Mapping):
            return {self.apply(key): self.apply(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.apply(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.apply(item) for item in value)
        return value

    def _swap(self, found: re.Match[str]) -> str:
        return self._pairs.get(found.group(0), found.group(0))


def _is_time(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and value > TIMESTAMP_MIN


def _same_json(old: Any, new: Any, slack: float) -> bool:
    if _is_time(old) and _is_time(new):
        return abs(old - new) <= slack
    if isinstance(old, dict) and isinstance(new, dict):
        return old.keys() == new.keys() and all(_same_json(old[k], new[k], slack) for k in old)
    if isinstance(old, list) and isinstance(new, list):
        pairs = zip(old, new, strict=False)
        return len(old) == len(new) and all(_same_json(a, b, slack) for a, b in pairs)
    return old == new and isinstance(old, bool) == isinstance(new, bool)


def same_result(
    recorded: Mapping[str, Any], outcome: ToolOutcome, *, copy_dir: str, data_dir: str
) -> bool:
    """Whether a replayed tool result is the recorded one, ids, data directory and clock jitter
    aside (spec §11)."""
    if bool(recorded.get("is_error")) != outcome.is_error:
        return False
    replayed = outcome.content.replace(copy_dir, data_dir) if copy_dir else outcome.content
    old, new = mask_ids(str(recorded.get("content", ""))), mask_ids(replayed)
    if old == new:
        return True
    try:
        old_json, new_json = json.loads(old), json.loads(new)
    except ValueError:
        return False
    slack = float(recorded.get("seconds") or 0.0) + TIME_SLACK_SECONDS
    return _same_json(old_json, new_json, slack)


def _denied_code(content: str | None) -> str | None:
    found = DENIED_PATTERN.match(content) if content else None
    return found.group(1) if found else None


class StepResult(Model):
    index: int  # position among the recorded tool lines (and the replay's tool calls), from 0
    turn: int
    name: str
    external: bool
    same: bool
    recorded: str
    replayed: str | None  # None when the replay did not run this call
    denied_code: str | None  # the code of a replayed refusal, shown apart (spec §11.4)
    note: str = ""
    input: Any = None  # the recorded tool input (the replayed one when the record has no line)


class ReplayReport(Model):
    warnings: tuple[str, ...]
    steps: tuple[StepResult, ...]
    recorded_end: dict[str, Any] | None
    replayed_end: RunEnd | None
    stopped: str | None
    exit_code: int
    unused_replies: int = 0  # recorded model replies the replay never asked for (a difference)


class ReplayToolset:
    """The toolset of a replayed run (same public API as ``Toolset``): each call takes the next
    recorded tool line and is compared with it; external tools only ever return the record."""

    def __init__(
        self,
        inner: Toolset,
        lines: Sequence[dict],
        clock: ReplayClock,
        ids: IdMap,
        *,
        copy_dir: str = "",
        data_dir: str = "",
        keep_going: bool = False,
        turn: Callable[[], int] = lambda: 0,
    ):
        self._inner = inner
        self._lines = tuple(lines)
        self._clock = clock
        self._ids = ids
        self._copy_dir, self._data_dir = copy_dir, data_dir
        self._keep_going = keep_going
        self._turn = turn
        self._steps: list[StepResult] = []

    @property
    def names(self) -> tuple[str, ...]:
        return self._inner.names

    def schemas(self, restricted: bool = False) -> list[dict]:
        return self._inner.schemas(restricted)

    def reads_web(self, name: str) -> bool:
        return self._inner.reads_web(name)

    def external(self, name: str) -> bool:
        return self._inner.external(name)

    def gate(self, name: str, raw_input: Any, restricted: bool = False) -> ToolOutcome | None:
        return self._inner.gate(name, raw_input, restricted)

    @property
    def steps(self) -> tuple[StepResult, ...]:
        return tuple(self._steps)

    @property
    def used(self) -> int:
        """How many recorded tool lines the replay has taken (one per call while any is left)."""
        return min(len(self._steps), len(self._lines))

    async def call(self, name: str, raw_input: Any, restricted: bool = False) -> ToolOutcome:
        index = len(self._steps)
        line = self._lines[index] if index < len(self._lines) else None
        if line is not None:
            self._clock.set(line["at"])
        given = self._ids.apply(raw_input)
        if line is None or line.get("name") != name:
            return await self._unmatched(index, line, name, given, restricted)
        external = bool(line.get("external")) or self._inner.external(name)
        if external:
            outcome, ran, note = self._external(line, name, given, restricted)
        else:
            outcome = ran = await self._inner.call(name, given, restricted)
            note = ""
        self._ids.learn(str(line["content"]), outcome.content)
        same = not note and same_result(
            line, outcome, copy_dir=self._copy_dir, data_dir=self._data_dir
        )
        self._steps.append(
            StepResult(
                index=index,
                turn=line["turn"],
                name=name,
                external=external,
                same=same,
                recorded=line["content"],
                replayed=ran.content if ran is not None else None,
                denied_code=_denied_code(ran.content) if ran is not None else None,
                note=note,
                input=line.get("input"),
            )
        )
        if not same and not self._keep_going:
            raise ReplayStop(f"step {index + 1} ({name}) differs from the record")
        return outcome

    def _external(
        self, line: Mapping[str, Any], name: str, given: Any, restricted: bool
    ) -> tuple[ToolOutcome, ToolOutcome | None, str]:
        """An external step: the gate runs as the code is now, the handler never does. Returns
        what the run gets, what the replay produced (None when nothing could be), and a note.

        A refusal of the gate now is the replayed result. Otherwise the recorded result stands,
        unless the record was itself a gate refusal: then the gate opened, which is a mismatch."""
        refused = self._inner.gate(name, given, restricted)
        if refused is not None:
            return refused, refused, ""
        recorded = ToolOutcome(name=name, content=line["content"], is_error=line["is_error"])
        if is_gate_refusal(name, recorded):
            return recorded, None, GATE_OPENED
        return recorded, recorded, ""

    async def _unmatched(
        self, index: int, line: dict | None, name: str, given: Any, restricted: bool
    ) -> ToolOutcome:
        """A call the record does not have at this step: a mismatch. It runs only with
        ``keep_going``, and an external tool never runs (it gets an error result)."""
        note = NO_LINE_LEFT if line is None else f"the record has {line.get('name')} here"
        external = self._inner.external(name)
        ran = None
        if self._keep_going and not external:
            ran = await self._inner.call(name, given, restricted)
        self._steps.append(
            StepResult(
                index=index,
                turn=self._turn(),
                name=name,
                external=external,
                same=False,
                recorded=str(line.get("content", "")) if line is not None else "",
                replayed=ran.content if ran is not None else None,
                denied_code=_denied_code(ran.content) if ran is not None else None,
                note=note,
                input=line.get("input") if line is not None else given,
            )
        )
        if not self._keep_going:
            raise ReplayStop(f"step {index + 1} ({name}): {note}")
        return ran or ToolOutcome(name=name, content=f"Error: {note}", is_error=True)


MakeDispatcher = Callable[[ModelClient, ReplayBudget, Mapping[str, RoleModel]], Dispatcher]


def _cannot(trace: Trace, message: str) -> ReplayReport:
    return ReplayReport(
        warnings=(message,),
        steps=(),
        recorded_end=trace.end,
        replayed_end=None,
        stopped=None,
        exit_code=EXIT_CANNOT,
    )


def _roles(run: Mapping[str, Any]) -> dict[str, RoleModel]:
    """The recorded role configuration; none when the role had no model configured."""
    config = run.get("role_config")
    return {} if config is None else {run["role"]: RoleModel.model_validate(config)}


def _prepare(
    run: Mapping[str, Any], make: MakeDispatcher, client: ReplayClient, budget: ReplayBudget
) -> tuple[Dispatcher, ResearchTask] | str:
    """The dispatcher and the task to replay, or why the record cannot be replayed here."""
    try:
        roles = _roles(run)
    except ValidationError as exc:
        return f"the recorded role configuration is not valid now: {exc}"
    dispatcher = make(client, budget, roles)
    try:
        return dispatcher, dispatcher.tasks.get(run["task_id"])
    except Denied as exc:
        return f"task {run['task_id']} cannot be found in this state: {exc}"


def _budget_refusal(end: Mapping[str, Any]) -> Mapping[str, Any] | None:
    denied = end.get("denied")
    return denied if isinstance(denied, Mapping) and denied.get("code") == "budget" else None


def _newer_state(dispatcher: Dispatcher, task: ResearchTask, run: Mapping[str, Any]) -> list[str]:
    out = []
    if task.state is not TaskState.IN_PROGRESS:
        out.append(
            f"the task is {task.state.value}, not in_progress: this state is newer than the "
            "record, results may differ"
        )
    log = dispatcher.conversation
    last = log.last_seq(task.project_id) if log is not None else None
    if last is not None and last > (run.get("conversation_seq") or 0):
        out.append("the conversation has entries newer than the record: results may differ")
    return out


def _warnings(
    dispatcher: Dispatcher, task: ResearchTask, run: Mapping[str, Any], user: str
) -> tuple[str, ...]:
    """What makes this replay differ from the recorded run before it starts (warnings only)."""
    out = _newer_state(dispatcher, task, run)
    role = run["role"]
    spec = ROLES.get(role)
    if spec is None or sha256_json(spec.system) != run.get("system_sha256"):
        out.append("the system prompt differs from the recorded one")
    schemas = dispatcher.schemas_for(role)
    if (sha256_json(schemas) if schemas is not None else None) != run.get("tools_sha256"):
        out.append("the tool definitions differ from the recorded ones")
    if mask_ids(user) != mask_ids(str(run.get("user", ""))):
        out.append("the first message differs from the recorded one (ids aside)")
    return tuple(out)


def _same_end(recorded: Mapping[str, Any], replayed: RunEnd | None) -> bool:
    if replayed is None or replayed.code != recorded.get("code"):
        return False
    if replayed.code != "denied":
        return True
    recorded_code = (recorded.get("params") or {}).get("denied_code")
    return replayed.params.get("denied_code") == recorded_code


def _unused_step(index: int, line: Mapping[str, Any]) -> StepResult:
    return StepResult(
        index=index,
        turn=int(line.get("turn") or 0),
        name=str(line.get("name", "")),
        external=bool(line.get("external")),
        same=False,
        recorded=str(line.get("content", "")),
        replayed=None,
        denied_code=None,
        note=NOT_CALLED,
        input=line.get("input"),
    )


def _report(
    trace: Trace,
    warnings: tuple[str, ...],
    toolset: ReplayToolset | None,
    client: ReplayClient,
    end: RunEnd | None,
    stopped: str | None,
) -> ReplayReport:
    """Every step, both ends and the exit code. Recorded lines the replay never took (tool
    lines and model replies) are a mismatch too, unless the replay stopped early (then they
    are expected)."""
    steps = list(toolset.steps) if toolset is not None else []
    models_left = max(len(trace.models) - client.served, 0) if stopped is None else 0
    if stopped is None:
        used = toolset.used if toolset is not None else 0
        steps += [_unused_step(used + n, line) for n, line in enumerate(trace.tools[used:])]
    same = all(s.same for s in steps) and _same_end(trace.end or {}, end)
    clean = same and stopped is None and models_left == 0
    return ReplayReport(
        warnings=warnings,
        steps=tuple(steps),
        recorded_end=trace.end,
        replayed_end=end,
        stopped=stopped,
        exit_code=EXIT_SAME if clean else EXIT_DIFFERENT,
        unused_replies=models_left,
    )


async def _replay(
    dispatcher: Dispatcher, task_id: str, client: ReplayClient, wrap: Callable[[Toolset], Any]
) -> tuple[RunEnd | None, str | None]:
    """The replayed end, or why the replay stopped before the run ended."""
    try:
        replayed = await dispatcher.replay_run(task_id, client, wrap)
    except (ReplayStop, ReplayExhausted) as exc:
        return None, str(exc)
    return replayed.end, None


async def replay_trace(
    trace: Trace,
    make: MakeDispatcher,
    clock: ReplayClock,
    *,
    copy_dir: str = "",
    keep_going: bool = False,
) -> ReplayReport:
    """Re-run a recorded run on the dispatcher ``make`` builds and compare it with the record."""
    if trace.end is None:
        return _cannot(trace, INCOMPLETE)
    run = trace.run
    client = ReplayClient(trace.models, clock)
    budget = ReplayBudget(len(trace.models), _budget_refusal(trace.end))
    prepared = _prepare(run, make, client, budget)
    if isinstance(prepared, str):
        return _cannot(trace, prepared)
    dispatcher, task = prepared
    user = dispatcher.message_for(task)
    warnings = _warnings(dispatcher, task, run, user)
    ids = IdMap()
    ids.learn(str(run.get("user", "")), user)
    clock.set(run["at"])
    made: list[ReplayToolset] = []

    def wrap(inner: Toolset) -> ReplayToolset:
        data_dir = str(run.get("data_dir") or "")
        made.append(
            ReplayToolset(
                inner,
                trace.tools,
                clock,
                ids,
                copy_dir=copy_dir,
                data_dir=data_dir,
                keep_going=keep_going,
                turn=lambda: client.served,
            )
        )
        return made[-1]

    end, stopped = await _replay(dispatcher, task.id, client, wrap)
    return _report(trace, warnings, made[-1] if made else None, client, end, stopped)
