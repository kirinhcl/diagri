"""Model traces: a JSONL record of every model call and tool call of one run.

``RunTrace`` owns one file; ``TracingClient`` and ``TracingToolset`` wrap the model client and
the toolset of ``run_agent`` and record what passes through them without changing it. A failure
to write is logged and ends the recording; it never reaches the run.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import os
import secrets
import subprocess
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from growbridge.agents.llm import ModelClient, ModelReply
from growbridge.agents.tools import ToolOutcome, Toolset
from growbridge.archive.clock import Clock
from growbridge.archive.models import Model

log = logging.getLogger(__name__)

TRACE_FORMAT = 1
TRACE_DIR = "model_traces"
PRE_RUN_SUFFIX = ".pre"
OPEN_ATTEMPTS = 5
GIT_TIMEOUT_SECONDS = 2


def content_dicts(content: Any) -> list[dict]:
    """The assistant content as plain dicts, thinking blocks kept whole."""
    if content is None:
        return []
    blocks: list[dict] = []
    for block in content:
        if isinstance(block, dict):
            blocks.append(block)
        elif hasattr(block, "model_dump"):
            blocks.append(block.model_dump(mode="json"))
        else:
            blocks.append({"type": "unknown", "repr": repr(block)})
    return blocks


def sha256_json(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@functools.cache
def git_commit() -> str | None:
    """The commit of the installed package, or None when it is not a git checkout."""
    try:
        done = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=True,
        )
    except Exception:
        return None
    return done.stdout.strip() or None


class Trace(Model):
    run: dict[str, Any]
    models: tuple[dict[str, Any], ...] = ()
    tools: tuple[dict[str, Any], ...] = ()
    end: dict[str, Any] | None = None


class TraceFormatError(ValueError):
    """A trace file that cannot be read; ``partial`` holds the lines before the bad one."""

    def __init__(self, message: str, partial: Trace | None = None):
        super().__init__(message)
        self.partial = partial


def _parse_line(number: int, text: str) -> dict[str, Any]:
    try:
        line = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TraceFormatError(f"line {number} is not valid JSON: {exc}") from exc
    if not isinstance(line, dict):
        raise TraceFormatError(f"line {number} is not an object")
    return line


def _check_run(line: dict[str, Any]) -> None:
    if line.get("kind") != "run" or line.get("format") != TRACE_FORMAT:
        raise TraceFormatError(f"first line is not a run line of format {TRACE_FORMAT}")


def _assemble(run: dict[str, Any], rest: Sequence[dict[str, Any]]) -> Trace:
    ends = [line for line in rest if line["kind"] == "end"]
    return Trace(
        run=run,
        models=tuple(line for line in rest if line["kind"] == "model"),
        tools=tuple(line for line in rest if line["kind"] == "tool"),
        end=ends[-1] if ends else None,
    )


def read_trace(path: Path) -> Trace:
    texts = Path(path).read_text(encoding="utf-8").splitlines()
    if not texts:
        raise TraceFormatError("trace file is empty")
    run = _parse_line(1, texts[0])
    _check_run(run)
    rest: list[dict[str, Any]] = []
    for number, text in enumerate(texts[1:], start=2):
        try:
            line = _parse_line(number, text)
            if line.get("kind") not in ("model", "tool", "end"):
                raise TraceFormatError(f"line {number} has unknown kind {line.get('kind')!r}")
        except TraceFormatError as exc:
            raise TraceFormatError(str(exc), partial=_assemble(run, rest)) from exc
        rest.append(line)
    return _assemble(run, rest)


class RunTrace:
    """The trace file of one run. Never raises from a write."""

    def __init__(self, path: Path, file: Any, clock: Clock):
        self.path = path
        self._file = file
        self._clock = clock
        self._begun = False
        self._turn = 0
        self._pending_ids: deque[str] = deque()

    @classmethod
    def open(
        cls,
        root: Path,
        task_id: str,
        clock: Clock,
        local: datetime,
        suffix: Callable[[], str] = lambda: secrets.token_hex(2),
    ) -> RunTrace | None:
        try:
            folder = Path(root) / local.strftime("%Y-%m-%d")
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            stem = f"{task_id}-{local.strftime('%H%M%S')}"
            for _ in range(OPEN_ATTEMPTS):
                path = folder / f"{stem}-{suffix()}.jsonl"
                try:
                    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    continue
                return cls(path, os.fdopen(descriptor, "w", encoding="utf-8"), clock)
            raise FileExistsError(f"no free trace file name for {stem}")
        except OSError:
            log.exception("cannot open a model trace under %s", root)
            return None

    def _write(self, line: Mapping[str, Any]) -> None:
        if self._file is None:
            return
        try:
            self._file.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
            self._file.flush()
        except Exception:
            log.exception("cannot write the model trace %s; recording stops", self.path)
            self._close()

    def _write_built(self, build: Callable[[], Mapping[str, Any]]) -> None:
        """Write the line ``build`` makes; a line that cannot be built stops the recording just
        as a failed write does, and never reaches the run."""
        if self._file is None:
            return
        try:
            line = build()
        except Exception:
            log.exception("cannot build a line of the model trace %s; recording stops", self.path)
            self._close()
            return
        self._write(line)

    def _close(self) -> None:
        file, self._file = self._file, None
        if file is None:
            return
        try:
            file.close()
        except Exception:
            log.exception("cannot close the model trace %s", self.path)

    def begin(self, header: Mapping[str, Any]) -> None:
        if self._begun:
            return
        self._begun = True
        self._write({"kind": "run", "format": TRACE_FORMAT, **header})

    def end(self, fields: Mapping[str, Any]) -> None:
        self._write({"kind": "end", **fields})
        self._close()

    def client(self, inner: ModelClient) -> TracingClient:
        return TracingClient(self, inner)

    def toolset(self, inner: Toolset) -> TracingToolset:
        return TracingToolset(self, inner)


class TracingClient:
    def __init__(self, trace: RunTrace, inner: ModelClient):
        self._trace = trace
        self._inner = inner

    async def create(self, **request: Any) -> ModelReply:
        trace = self._trace
        trace._turn += 1
        turn = trace._turn
        at = trace._clock.now()
        started = time.monotonic()
        try:
            reply = await self._inner.create(**request)
        except Exception as exc:
            seconds = time.monotonic() - started
            trace._write_built(functools.partial(_error_line, turn, at, seconds, exc))
            raise
        seconds = time.monotonic() - started
        trace._pending_ids = deque(c.id for c in reply.tool_calls)
        trace._write_built(functools.partial(_reply_line, turn, at, seconds, reply))
        return reply


def _error_line(turn: int, at: float, seconds: float, exc: Exception) -> dict[str, Any]:
    error = f"{type(exc).__name__}: {exc}"
    return {"kind": "model", "turn": turn, "at": at, "seconds": seconds, "error": error}


def _reply_line(turn: int, at: float, seconds: float, reply: ModelReply) -> dict[str, Any]:
    return {
        "kind": "model",
        "turn": turn,
        "at": at,
        "seconds": seconds,
        "stop_reason": reply.stop_reason,
        "text": reply.text,
        "tool_calls": [{"id": c.id, "name": c.name, "input": c.input} for c in reply.tool_calls],
        "content": content_dicts(reply.content),
        "input_tokens": reply.input_tokens,
        "output_tokens": reply.output_tokens,
    }


class TracingToolset:
    def __init__(self, trace: RunTrace, inner: Toolset):
        self._trace = trace
        self._inner = inner

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

    async def call(self, name: str, raw_input: Any, restricted: bool = False) -> ToolOutcome:
        trace = self._trace
        tool_use_id = trace._pending_ids.popleft() if trace._pending_ids else None
        at = trace._clock.now()
        started = time.monotonic()
        outcome = await self._inner.call(name, raw_input, restricted)
        trace._write(
            {
                "kind": "tool",
                "turn": trace._turn,
                "at": at,
                "seconds": time.monotonic() - started,
                "tool_use_id": tool_use_id,
                "name": name,
                "input": raw_input,
                "content": outcome.content,
                "is_error": outcome.is_error,
                "external": self._inner.external(name),
            }
        )
        return outcome
