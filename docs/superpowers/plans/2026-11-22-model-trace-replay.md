# Model Trace and Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every model-role run completely (opt-in `model_trace`), list a recording step by step (`growbridge trace show`), and re-run it offline against a copy of the data directory with the recorded model replies (`growbridge trace replay`), reporting the first step whose tool result differs.

**Architecture:** The `Dispatcher` opens one `RunTrace` per run; a client wrapper records model calls and a toolset wrapper records tool calls, so `run_agent` is untouched. The run-end decision moves into pure functions so a real run and a replay end the same way. Replay builds a runtime on a temporary copy of the data directory (a pre-run copy the dev workbench makes, when there is one), feeds the recorded replies through a replay client, returns recorded results for `external` tools, runs every other tool for real, and compares results after masking ids, paths and clock jitter.

**Tech Stack:** Python 3.11+ standard library (`json`, `sqlite3`, `hashlib`, `re`, `shutil`, `tempfile`, `subprocess` for `git rev-parse`), the project's pydantic `Model`, pytest with `asyncio_mode = "auto"`.

**Spec:** `docs/superpowers/specs/2026-11-22-model-trace-replay-design.md` (Chinese). §N below refers to its sections.

## Global Constraints

- Python `>=3.11`; ruff rule sets `E`, `F`, `I`, `B`, `UP`, line length 100; `ruff format` clean.
- New value types subclass `growbridge.archive.models.Model` (frozen, `extra="forbid"`). Writers and wrappers that hold a file handle or counters are plain classes.
- Files stay under 800 lines; functions under 50 lines.
- `Settings.model_trace: bool = False`. Trace root `data_dir / "model_traces"`, directories mode 0700 (`private_dir`), trace files mode 0600.
- Trace path `model_traces/<YYYY-MM-DD>/<task_id>-<HHMMSS>-<4 hex>.jsonl`, local time of the run start. Pre-run copy directory: the trace path with `.jsonl` replaced by `.pre`.
- Trace line kinds `run`, `model`, `tool`, `end`; `format` is `1`. Field names exactly as spec §7.
- `external` tools are exactly: `lookup_crop_conditions`, `search_and_verify_sources`, `submit_compute_job`, `get_compute_job`, `fetch_compute_artifacts`.
- A failure to write a trace or make a pre-run copy is logged with `log.exception` and never changes the run.
- Replay never writes the source directory or a pre-run copy, never calls `runtime.start()`, and builds the runtime with `channels={}`, no heartbeats, no compute backend, a `SimulatedTransport`.
- Id pattern `\b([a-z][a-z0-9]*)_[0-9a-f]{32}\b`, masked as `\1_*`. Timestamp tolerance: two JSON numbers both `> 1e9` match when they differ by at most the recorded tool `seconds` + 1.
- Replay exit codes: `0` all steps and the end match, `1` a mismatch, `2` cannot replay.
- Tests never touch the network.
- Docs change in both `docs/wiki/en/` and `docs/wiki/zh-CN/`.
- Commit messages: `<type>: <subject>`, a body, then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Before each commit that touches code, run the `verify` skill (docs-only commits skip it). Commits stay on branch `worktree-model-trace-replay`; nothing is pushed.

## Review Focus

1. A reply whose first tool call has invalid input: the tool line for the second call must still carry the second `tool_use_id` (ids are paired by order, and an invalid call still consumes one). Test in Task 2.
2. A trace whose last line was cut off by a crash: `read_trace` raises `TraceFormatError`, `trace show` prints what it can and says the record is incomplete, `trace replay` exits 2. Tests in Tasks 2, 6, 8.
3. Two runs of the same task starting in the same second: the second trace gets a different file name, never overwrites. Test in Task 2.
4. A source database in WAL mode with writes not yet checkpointed: the copy contains them. Test in Task 3.
5. A data directory whose path is a prefix of another path (`/x/data` vs `/x/database`): relocation rewrites only the first. Test in Task 3.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/growbridge/agents/tools.py` (modify) | `Tool.external`, `Toolset.external(name)` |
| `src/growbridge/agents/handlers_planner.py`, `handlers_researcher.py` (modify) | mark the five external tools |
| `src/growbridge/agents/trace.py` (create) | trace format, `RunTrace` writer, client and toolset recorders, `read_trace` |
| `src/growbridge/archive/datacopy.py` (create) | copy a data directory safely; rewrite stored absolute paths |
| `src/growbridge/agents/run_end.py` (create) | `RunEnd` and the pure run-end decision, moved out of `run_task` |
| `src/growbridge/agents/dispatch.py` (modify) | `TraceSettings`, tracing in `run_task`, `message_for`, `schemas_for`, `replay_run` |
| `src/growbridge/agents/conversation.py` (modify) | `last_seq` |
| `src/growbridge/config.py`, `runtime.py`, `runtime_agents.py` (modify) | `model_trace`, `Runtime.pre_run_copies`, `make_dispatcher` wiring and overrides |
| `src/growbridge/agents/trace_show.py` (create) | render a trace for the terminal |
| `src/growbridge/agents/replay.py` (create) | replay clock, client, budget, toolset; comparison; `replay_trace` |
| `src/growbridge/replay_runtime.py` (create) | choose the source, copy, relocate, build the replay runtime, `replay_file` |
| `src/growbridge/trace_cli.py` (create) + `cli.py` (modify) | `growbridge trace show` / `trace replay` |
| `scripts/dev_workbench.py` (modify) | `--trace` replaces `--transcript`; `RecordingClient` removed |
| `docs/wiki/{en,zh-CN}/*.md` (modify) | spec §13 |

---

### Task 1: External tool marker

**Files:**
- Modify: `src/growbridge/agents/tools.py:101-108` (dataclass `Tool`), `:190-192` (next to `reads_web`)
- Modify: `src/growbridge/agents/handlers_planner.py:152-165`, `src/growbridge/agents/handlers_researcher.py:388-402`
- Test: `tests/dispatch/test_agents_external_tools.py`

**Interfaces:**
- Produces: `Tool.external: bool = False`; `Toolset.external(name: str) -> bool` (False for an unknown name, like `reads_web`).

- [ ] **Step 1: Write the failing tests**

```python
EXPECTED = {
    "lookup_crop_conditions", "search_and_verify_sources",
    "submit_compute_job", "get_compute_job", "fetch_compute_artifacts",
}

def test_every_web_tool_is_external(env):
    for tools in env.tools().values():
        for tool in tools:
            if tool.reads_web:
                assert tool.external, tool.name

def test_external_tools_are_exactly_the_reviewed_list(env):
    names = {t.name for tools in env.tools().values() for t in tools if t.external}
    assert names == EXPECTED

def test_toolset_reports_external_by_name(env):
    toolset = build_toolset("planner", env.tools()["planner"])
    assert toolset.external("search_and_verify_sources")
    assert not toolset.external("validate_run_sheet")
    assert not toolset.external("no_such_tool")
```

`env` is the fixture of `tests/dispatch/conftest.py`. If `env.tools()` omits the compute tools when no compute service is configured, build the researcher tools with a deps object that has one (see how `tests/dispatch/test_dispatch_researcher.py` does it).

- [ ] **Step 2: Run and see them fail**

Run: `.venv/bin/pytest tests/dispatch/test_agents_external_tools.py -q`
Expected: FAIL (`Tool` has no attribute `external`).

- [ ] **Step 3: Add `external` to `Tool` and `Toolset.external(name)`; pass `external=True` on the five tools**

- [ ] **Step 4: Run the tests and the agents and dispatch suites**

Run: `.venv/bin/pytest tests/dispatch tests/agents -q`
Expected: all pass.

- [ ] **Step 5: Commit** — `feat: mark tools that reach outside the machine as external`

---

### Task 2: Trace format and recorders

**Files:**
- Create: `src/growbridge/agents/trace.py`
- Test: `tests/agents/test_trace_writer.py`

**Interfaces:**
- Consumes: `Toolset` public API (`names`, `schemas(restricted)`, `reads_web(name)`, `external(name)`, `async call(name, raw_input, restricted)`), `ModelClient.create(**request) -> ModelReply`, `Clock` (`now()`, `monotonic()`, `synced`).
- Produces:
  - constants `TRACE_FORMAT = 1`, `TRACE_DIR = "model_traces"`, `PRE_RUN_SUFFIX = ".pre"`
  - `content_dicts(content: Any) -> list[dict]` — dicts kept, objects with `model_dump` → `model_dump(mode="json")`, `None` → `[]`, anything else → `{"type": "unknown", "repr": repr(block)}`
  - `sha256_json(value: Any) -> str` — SHA-256 hex of `json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)`
  - `git_commit() -> str | None` — `git -C <package dir> rev-parse HEAD`, 2 s timeout, cached, `None` on any failure
  - `class TraceFormatError(ValueError)`
  - `class Trace(Model)`: `run: dict[str, Any]`, `models: tuple[dict[str, Any], ...]`, `tools: tuple[dict[str, Any], ...]`, `end: dict[str, Any] | None`
  - `read_trace(path: Path) -> Trace`
  - `class RunTrace`: `open(root: Path, task_id: str, clock: Clock, local: datetime, suffix: Callable[[], str] = lambda: secrets.token_hex(2)) -> RunTrace | None` (classmethod), `path: Path`, `begin(header: Mapping[str, Any]) -> None`, `client(inner) -> TracingClient`, `toolset(inner) -> TracingToolset`, `end(fields: Mapping[str, Any]) -> None`
  - `TracingClient.create(**request)` and `TracingToolset` (same public API as `Toolset`)

Behaviour pinned by the spec and these tests:
- `open` makes `root/<local:%Y-%m-%d>` with `private_dir`, creates `<task_id>-<local:%H%M%S>-<suffix()>.jsonl` with `os.open(..., O_WRONLY | O_CREAT | O_EXCL, 0o600)`, retries with a new suffix on `FileExistsError` up to 5 times, returns `None` (after `log.exception`) on any `OSError`.
- Every line is `json.dumps(line, ensure_ascii=False, default=str)`, written and flushed at once. The first failed write logs, closes the file, and turns every later call into a no-op. The recorder never raises.
- `begin` writes `{"kind": "run", "format": 1, **header}` once; later calls are ignored.
- `TracingClient.create` sets `turn` (1, 2, …), reads `at = clock.now()` and `time.monotonic()` before calling the inner client, and writes a `model` line with `stop_reason`, `text`, `tool_calls` (`id`, `name`, `input`), `content` (via `content_dicts`), tokens, `seconds`. On an exception it writes `error: "<Type>: <message>"` and re-raises unchanged. It remembers the reply's tool-call ids in order.
- `TracingToolset.call` takes the next remembered id (`None` when none are left), reads `at` before delegating, and writes a `tool` line with `turn`, `at`, `seconds`, `tool_use_id`, `name`, `input`, `content`, `is_error`, `external` (from `inner.external(name)`). It returns the inner outcome object unchanged.
- `end` writes `{"kind": "end", **fields}` and closes.
- `read_trace` raises `TraceFormatError` when the first line is not a `run` line with `format == 1`, when any line is not valid JSON, or when a line has an unknown `kind`. A file without an `end` line is valid (`end=None`).

- [ ] **Step 1: Write the failing tests**

```python
async def test_records_a_run_line_model_lines_tool_lines_and_an_end(tmp_path, clock):
    trace = RunTrace.open(tmp_path, "task-1", clock, datetime(2026, 11, 22, 9, 5, 7))
    trace.begin({"task_id": "task-1"})
    client = trace.client(ScriptedClient([tool_reply(call("echo", "c1")), text_reply("done")]))
    toolset = trace.toolset(build_toolset("planner", [make_tool("echo")]))
    reply = await client.create(model="m", system="s", messages=[], tools=[], max_tokens=1, effort="low")
    await toolset.call("echo", {"value": "x"})
    await client.create(model="m", system="s", messages=[], tools=[], max_tokens=1, effort="low")
    trace.end({"code": "run_finished"})
    lines = [json.loads(l) for l in trace.path.read_text().splitlines()]
    assert [l["kind"] for l in lines] == ["run", "model", "tool", "model", "end"]
    assert lines[0]["format"] == 1
    assert lines[2]["tool_use_id"] == "c1" and lines[2]["turn"] == 1
    assert lines[1]["tool_calls"] == [{"id": "c1", "name": "echo", "input": reply.tool_calls[0].input}]
    assert trace.path.parent.name == "2026-11-22"
    assert trace.path.name.startswith("task-1-090507-")

def test_files_are_0600_and_dirs_0700(tmp_path, clock): ...
def test_thinking_blocks_are_kept_whole_from_objects_and_dicts(): ...
    # content_dicts([SdkLike(type="thinking", thinking="t", signature="sig"), {"type": "redacted_thinking", "data": "x"}])
    # == [{"type": "thinking", "thinking": "t", "signature": "sig"}, {"type": "redacted_thinking", "data": "x"}]
async def test_tool_results_are_not_clipped(tmp_path, clock): ...      # 20 000-character result kept whole
async def test_model_error_is_recorded_and_re_raised(tmp_path, clock): ...
async def test_a_failing_write_never_raises_and_stops_writing(tmp_path, clock, monkeypatch): ...
async def test_invalid_first_call_keeps_the_second_id(tmp_path, clock):           # Review Focus 1
    # reply with calls c1 (invalid input) and c2; both tool lines carry their own id in order
def test_same_second_runs_get_different_files(tmp_path, clock):                    # Review Focus 3
    # suffix returns "aaaa", "aaaa", "bbbb": first file -aaaa, second -bbbb
def test_read_trace_rejects_a_cut_off_last_line(tmp_path):                         # Review Focus 2
    # valid run + model lines, then '{"kind": "tool", "na' -> TraceFormatError
def test_read_trace_accepts_a_file_without_end(tmp_path): ...                       # end is None
def test_read_trace_rejects_unknown_format(tmp_path): ...                           # format 2
```

`call`, `tool_reply`, `text_reply`, `make_tool` come from `tests/dispatch_helpers.py`, `growbridge/sim/llm.py` and `tests/agents/agent_helpers.py`; `clock` is a `FakeClock`.

- [ ] **Step 2: Run and see them fail** — `.venv/bin/pytest tests/agents/test_trace_writer.py -q`, expected: ImportError.
- [ ] **Step 3: Implement `src/growbridge/agents/trace.py` with the interfaces above**
- [ ] **Step 4: Run the tests** — expected: PASS.
- [ ] **Step 5: Commit** — `feat: add the model trace format and its recorders`

---

### Task 3: Copy a data directory and relocate stored paths

**Files:**
- Create: `src/growbridge/archive/datacopy.py`
- Test: `tests/archive/test_datacopy.py`

**Interfaces:**
- Consumes: `copy_database(source_path: str, partial: Path)` from `growbridge.archive.backup`, `TRACE_DIR` from Task 2.
- Produces:
  - `copy_data_dir(source: Path, target: Path) -> None` — `target` must not exist (raise `FileExistsError`); created 0700. Every `*.sqlite3` at any depth is copied with `copy_database`; `*-wal`, `*-shm`, `*-journal` and the `TRACE_DIR` directory are skipped; every other file is copied with `shutil.copy2`; directories are created 0700.
  - `relocate_paths(data_dir: Path, old: str, new: str) -> int` — in every `*.sqlite3` under `data_dir`, for every table and every column whose declared type contains `TEXT` (`PRAGMA table_info`), replace `old + "/"` with `new + "/"` and set values equal to `old` to `new`; returns the number of rows changed. One transaction per database.

- [ ] **Step 1: Write the failing tests**

```python
def test_copies_databases_files_and_skips_traces(tmp_path): ...
    # source has archive.sqlite3 (one row), agent_work/reports/r.json, host_id, model_traces/x.jsonl
    # copy has the row, the report, host_id; no model_traces
def test_copy_includes_uncheckpointed_wal_writes(tmp_path):                         # Review Focus 4
    db = sqlite3.connect(src / "a.sqlite3"); db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE t(v TEXT)"); db.execute("INSERT INTO t VALUES ('x')"); db.commit()
    # keep `db` open (no checkpoint), copy, then the copy holds 'x'
def test_target_must_not_exist(tmp_path): ...                                       # FileExistsError
def test_copy_dirs_are_0700(tmp_path): ...
def test_relocate_rewrites_paths_inside_json_bodies(tmp_path):
    # body '{"path": "/x/data/agent_work/r.json"}' -> '{"path": "/y/copy/agent_work/r.json"}'; returns 1
def test_relocate_leaves_a_longer_sibling_path_alone(tmp_path):                     # Review Focus 5
    # '/x/database/a' unchanged while '/x/data/a' changes
def test_relocate_skips_non_text_columns(tmp_path): ...
```

- [ ] **Step 2: Run and see them fail** — `.venv/bin/pytest tests/archive/test_datacopy.py -q`.
- [ ] **Step 3: Implement `datacopy.py`**
- [ ] **Step 4: Run the tests** — expected: PASS.
- [ ] **Step 5: Commit** — `feat: copy a live data directory and relocate its stored paths`

---

### Task 4: Run-end decision as pure functions, and a replay entry on the dispatcher

A pure refactor plus one new entry point; no tracing yet. Every existing dispatch test must still pass unchanged.

**Files:**
- Create: `src/growbridge/agents/run_end.py`
- Modify: `src/growbridge/agents/dispatch.py:184-282` (`run_task`, `_run`), move `DELIVERABLES`, `UNDELIVERED`, `REASON_CHARS` into `run_end.py` and import them back (grep for other importers first)
- Test: `tests/dispatch/test_dispatch_run_end.py`

**Interfaces:**
- Produces in `run_end.py`:
  - `class RunEnd(Model)`: `state: TaskState`, `reason: str`, `said: str = ""`, `code: str`, `params: dict[str, Any] = {}`, `denied: dict[str, Any] | None = None`
  - `class RunInterrupted(Exception)` — raised by a replay to stop a run; `replay_run` lets it through.
  - `end_of_run(run: AgentRun, owner_role: str, reviews: Sequence[bool], deliveries: Sequence[str]) -> RunEnd` — the `model_stopped` / `undelivered` / `run_finished` branches of today's `run_task`, same reasons, codes and params.
  - `end_of_denied(exc: Denied) -> RunEnd` — `code="denied"`, `params={"denied_code": exc.code}`, `reason=f"{exc.code}: {exc}"`, `denied={"code", "message": str(exc), "reason", "params"}`.
  - `end_of_error(exc: Exception) -> RunEnd` — `code="model_unavailable"`, reason as today.
- Produces in `dispatch.py`:
  - `ToolsetWrap = Callable[[Toolset], Toolset]`
  - `Dispatcher.message_for(task: ResearchTask) -> str` (today's `_message`, made public; keep `_message` as an alias only if tests use it)
  - `Dispatcher.schemas_for(role: str) -> list[dict] | None` — the schemas `_toolset` would offer, `None` when the role has no config or `build_toolset` raises `Denied`
  - `_run(self, task, user: str, reviews, deliveries, *, client: ModelClient, wrap: ToolsetWrap)` — the message is computed once by the caller
  - `class ReplayedRun(Model)`: `user: str`, `end: RunEnd`
  - `async def replay_run(self, task_id: str, client: ModelClient, wrap: ToolsetWrap) -> ReplayedRun` — `tasks.get(task_id)` (no `_claim`, any state), `message_for`, `_run`; maps `Denied` / other exceptions through `end_of_denied` / `end_of_error`, re-raises `RunInterrupted`; never calls `_end`, never writes `dispatch_claims`.
  - `run_task` keeps its behaviour: it calls `_end(task, end.state, end.reason, end.said, code=end.code, params=end.params)` with the `RunEnd` from the functions above.

- [ ] **Step 1: Write the failing tests**

```python
def test_end_of_run_matches_each_branch(): ...      # model_stopped (stop_reason "max_turns"), undelivered, run_finished, needs_review
def test_end_of_denied_keeps_the_whole_refusal():
    end = end_of_denied(Denied("budget", "call budget exhausted for project p", reason="budget_calls_exhausted", params={}))
    assert end.code == "denied" and end.params == {"denied_code": "budget"}
    assert end.denied == {"code": "budget", "message": "call budget exhausted for project p",
                          "reason": "budget_calls_exhausted", "params": {}}
async def test_replay_run_runs_a_finished_task_without_claiming_or_moving_it(env): ...
    # run a planner task to DONE with ScriptedClient, then replay_run it with a fresh ScriptedClient:
    # state stays DONE, dispatch_claims row count unchanged, ReplayedRun.end.code == "run_finished"
async def test_replay_run_lets_run_interrupted_through(env): ...
def test_schemas_for_a_role_and_for_a_bad_tool_list(env): ...  # list for "planner"; None when RoleModel(tools=["nope"])
```

- [ ] **Step 2: Run and see them fail** — `.venv/bin/pytest tests/dispatch/test_dispatch_run_end.py -q`.
- [ ] **Step 3: Create `run_end.py`; refactor `run_task` and `_run`; add `message_for`, `schemas_for`, `replay_run`**
- [ ] **Step 4: Run the new tests and the whole dispatch, agents and e2e suites** — `.venv/bin/pytest tests/dispatch tests/agents tests/e2e -q`, expected: all pass with no change to existing tests.
- [ ] **Step 5: Commit** — `refactor: decide a run's end in pure functions and add a replay entry`

---

### Task 5: Tracing in the dispatcher, the config switch and pre-run copies

**Files:**
- Modify: `src/growbridge/agents/dispatch.py` (`__init__`, `run_task`), `src/growbridge/agents/conversation.py`, `src/growbridge/config.py:57-92`, `src/growbridge/runtime.py:199` (`Runtime`), `src/growbridge/runtime_agents.py:71-88`
- Modify (test helper): `tests/dispatch_env.py:72` (`Env.dispatcher` gains `trace=None`)
- Test: `tests/dispatch/test_dispatch_trace.py`, `tests/e2e/test_e2e_trace_record.py`

**Interfaces:**
- Consumes: Task 2 (`RunTrace`, `sha256_json`, `git_commit`, `TRACE_DIR`, `PRE_RUN_SUFFIX`), Task 3 (`copy_data_dir`), Task 4 (`RunEnd`, `schemas_for`, `message_for`).
- Produces:
  - `@dataclass(frozen=True) class TraceSettings`: `root: Path`, `data_dir: Path`, `pre_run_copies: bool = False` (in `dispatch.py`)
  - `Dispatcher.__init__(..., conversation=None, trace: TraceSettings | None = None)`
  - `ConversationLog.last_seq(project_id: str) -> int | None`
  - `Settings.model_trace: bool = False`
  - `Runtime.pre_run_copies: bool = False` (dataclass field with a default)
  - `make_dispatcher(runtime, client, work_root, *, roles: Mapping[str, RoleModel] | None = None, budget: Any = None, tracing: bool = True) -> Dispatcher` — `roles` replaces the computed mapping entirely when given; `budget` replaces `runtime.budget`; tracing on only when `tracing` and `runtime.settings.model_trace`, with `TraceSettings(private_dir(data_dir / TRACE_DIR), data_dir, runtime.pre_run_copies)`.

In `run_task`, after `_claim` succeeds and only when `self.trace` is set: open the `RunTrace` (local time from `datetime.fromtimestamp(self.clock.now())`); when `pre_run_copies`, `copy_data_dir(data_dir, <trace path with .pre>)` inside `try/except Exception` with `log.exception`; then `begin` with the spec §7 header: `task_id`, `project_id`, `role`, `role_config` (`model_dump(mode="json")` or `None`), `system`, `system_sha256`, `tools` (names from `schemas_for`, or `None`), `tools_sha256` (`sha256_json(schemas)` or `None`), `user`, `conversation_seq`, `clock_synced` (`getattr(clock, "synced", None)`), `data_dir`, `pre_run_copy` (directory name or `None`), `growbridge_version`, `git_commit`, `at`. Run with `client=trace.client(self.client)`, `wrap=trace.toolset`. After the end is decided, `trace.end` with `at`, `state`, `code`, `reason`, `params`, `denied`, `turns`, `input_tokens`, `output_tokens`, `cost` (zeros when the run raised), `seconds`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_trace_off_writes_nothing(env, tmp_path): ...            # no model_traces dir
async def test_trace_on_writes_a_complete_file(env, tmp_path):
    # planner validates a sheet then answers; header fields of spec §7 all present,
    # role_config == RoleModel().model_dump(mode="json"), user == dispatcher.message_for(task),
    # one tool line with full content, end code "run_finished"
@pytest.mark.parametrize("case, code", [("stopped", "model_stopped"), ("undelivered", "undelivered"),
                                        ("finished", "run_finished"), ("denied", "denied"),
                                        ("error", "model_unavailable")])
async def test_end_line_carries_each_end_code(env, tmp_path, case, code): ...
async def test_budget_refusal_records_the_whole_denied(env, tmp_path): ...   # end.denied["code"] == "budget"
async def test_trace_failure_leaves_the_run_unchanged(env, tmp_path, monkeypatch):
    # RunTrace.open returns None (and, second case, write raises OSError): task state and conversation
    # entries equal those of the same run without tracing
def test_last_seq_is_none_for_an_empty_project_and_the_max_otherwise(db, clock): ...
```

`tests/e2e/test_e2e_trace_record.py` (uses `World`):

```python
async def test_pre_run_copy_holds_the_state_before_the_first_model_call(world): ...
    # settings.model_trace=True, runtime.pre_run_copies=True; run the planner step of
    # test_e2e_agents.test_model_driven_round_from_delegation_to_delivery;
    # the .pre copy exists, has no model_traces, and its round is still in planning (no draft yet)
async def test_serve_settings_never_make_a_copy(world): ...           # model_trace=True, pre_run_copies False -> no .pre
async def test_copy_failure_keeps_the_run_and_records_null(world, monkeypatch): ...
```

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement `TraceSettings`, tracing in `run_task`, `last_seq`, `model_trace`, `pre_run_copies`, `make_dispatcher` changes**
- [ ] **Step 4: Run** — `.venv/bin/pytest tests/dispatch tests/agents tests/e2e tests/test_config_greenhouses.py -q`, expected: all pass.
- [ ] **Step 5: Commit** — `feat: record model-role runs when model_trace is on`

---

### Task 6: `growbridge trace show`

**Files:**
- Create: `src/growbridge/agents/trace_show.py`, `src/growbridge/trace_cli.py`
- Modify: `src/growbridge/cli.py:204-248` (parser), `:250-270` (`main`, before `settings = load(args.config)`)
- Test: `tests/agents/test_trace_show.py`, `tests/test_trace_cli.py`

**Interfaces:**
- Consumes: `Trace`, `read_trace`, `TraceFormatError` (Task 2).
- Produces:
  - `SHORT_CHARS = 400`
  - `strip_controls(text: str) -> str` — removes ANSI escape sequences (`\x1b\[[0-?]*[ -/]*[@-~]` and OSC `\x1b\][^\x07]*\x07`) and every C0/C1 control character except `\n` and `\t`
  - `render_trace(trace: Trace, *, full: bool = False) -> str` — header summary (task, role, model, version, start time, pre-run copy yes/no), then per turn: thinking, text, each tool call (name, input, result, error flag), then the end (code, reason, turns, tokens, cost, seconds) or the line `Record incomplete: the run has no end line.`; every value passes `strip_controls`; values longer than `SHORT_CHARS` are cut with `… (N more characters, use --full)` unless `full`
  - `add_trace_parser(sub) -> None` — `trace show FILE [--full]` (and, in Task 8, `trace replay`)
  - `run_trace(args, load_settings: Callable[[], Settings]) -> int` — `show` never calls `load_settings`; prints `render_trace`; on `TraceFormatError` prints the error and whatever lines parsed, returns 2
  - `cli.main`: `if args.command == "trace": raise SystemExit(run_trace(args, lambda: load(args.config)))`

- [ ] **Step 1: Write the failing tests**

```python
def test_steps_come_out_in_order(sample_trace): ...        # thinking, text, tool name, end code appear in order
def test_long_values_are_cut_unless_full(sample_trace): ...
def test_control_characters_and_ansi_are_removed():
    assert strip_controls("a\x1b[31mred\x1b[0m\x07b\n") == "aredb\n"
def test_missing_end_says_incomplete(sample_trace_without_end): ...
def test_cli_show_needs_no_config(tmp_path, capsys): ...    # main(["trace","show",path]) with no config file: exit 0
def test_cli_show_cut_off_file_exits_2(tmp_path, capsys): ...
```

Build `sample_trace` by writing a trace with `RunTrace` (Task 2), not by hand.

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement `trace_show.py`, `trace_cli.py` (show only) and the `cli.py` wiring**
- [ ] **Step 4: Run** — `.venv/bin/pytest tests/agents/test_trace_show.py tests/test_trace_cli.py tests/e2e/test_e2e_cli.py -q`, expected: PASS.
- [ ] **Step 5: Commit** — `feat: list a model trace step by step with growbridge trace show`

---

### Task 7: Replay engine

**Files:**
- Create: `src/growbridge/agents/replay.py`
- Test: `tests/dispatch/test_replay.py`

**Interfaces:**
- Consumes: `Trace` (Task 2), `RunEnd`, `RunInterrupted` (Task 4), `Dispatcher.replay_run`, `message_for`, `schemas_for`, `tasks`, `conversation` (Tasks 4–5), `ROLES`, `RoleModel`, `ToolOutcome`, `ModelReply`, `ToolCall`, `Denied`.
- Produces:
  - `class ReplayClock`: `__init__(start: float, synced: bool | None = True)`, `synced` (`True` when `None` was recorded), `now() -> float`, `monotonic() -> float` (real `time.monotonic()`), `set(at: float) -> None`
  - `class ReplayedModelError(RuntimeError)`; `class ReplayExhausted(RunInterrupted)`; `class ReplayStop(RunInterrupted)`
  - `class ReplayClient`: `__init__(models: Sequence[dict], clock: ReplayClock)`; `async create(**request) -> ModelReply` — sets the clock to the line's `at`, rebuilds `ModelReply` from `stop_reason`, `text`, `tool_calls`, `content`, tokens; an `error` line raises `ReplayedModelError(line["error"])`; no line left raises `ReplayExhausted`
  - `class ReplayBudget`: `__init__(calls: int, refusal: Mapping[str, Any] | None)`; `reserve(project_id: str, calls: int = 1) -> None` — the first `calls` reservations pass; after that, if `refusal` is set raise `Denied(refusal["code"], refusal["message"], reason=refusal["reason"], params=refusal["params"])`, else pass; `charge(project_id, cost) -> None` does nothing. `refusal` is `trace.end["denied"]` only when its `code == "budget"`.
  - `mask_ids(text: str) -> str`
  - `class IdMap`: `learn(recorded: str, replayed: str) -> None` (pairs ids found by the pattern, in order, only when both texts have the same count), `apply(value: Any) -> Any` (deep copy with every known recorded id replaced in strings), `pairs -> dict[str, str]`
  - `same_result(recorded: Mapping[str, Any], outcome: ToolOutcome, *, copy_dir: str, data_dir: str) -> bool` — `is_error` equal; replayed content with `copy_dir` → `data_dir`; both through `mask_ids`; equal strings match; otherwise parse both as JSON and compare recursively with the timestamp tolerance of the Global Constraints
  - `class StepResult(Model)`: `index: int`, `turn: int`, `name: str`, `external: bool`, `same: bool`, `recorded: str`, `replayed: str | None`, `denied_code: str | None`, `note: str = ""`
  - `class ReplayReport(Model)`: `warnings: tuple[str, ...]`, `steps: tuple[StepResult, ...]`, `recorded_end: dict[str, Any] | None`, `replayed_end: RunEnd | None`, `stopped: str | None`, `exit_code: int`
  - `class ReplayToolset` (same public API as `Toolset`): wraps the real toolset; each `call` takes the next recorded tool line, sets the clock to its `at`, applies `IdMap` to the input, returns the recorded `ToolOutcome` when the line or the tool is `external` (handler never called), otherwise delegates; then `learn`s ids, compares with `same_result`, appends a `StepResult`, and raises `ReplayStop` on the first mismatch unless `keep_going`. A call with no recorded line left, or with a different tool name, is a mismatch.
  - `async def replay_trace(trace: Trace, make: Callable[[ModelClient, ReplayBudget, Mapping[str, RoleModel]], Dispatcher], clock: ReplayClock, *, copy_dir: str = "", keep_going: bool = False) -> ReplayReport`

`replay_trace` order: exit 2 when `trace.end is None`; roles = `{role: RoleModel.model_validate(cfg)}` or `{}` when `role_config` is `None`; build the dispatcher with `make`; exit 2 when the task is missing; warnings (task not `in_progress`; `conversation.last_seq` above `conversation_seq`; `sha256` of `ROLES[role].system` differs; `sha256_json(schemas_for(role))` differs; masked `message_for(task)` differs from masked `run["user"]`); seed `IdMap.learn(run["user"], message_for(task))`; `clock.set(run["at"])`; `replay_run(task_id, ReplayClient(...), wrap=lambda ts: ReplayToolset(ts, ...))`; on `ReplayStop` / `ReplayExhausted` record `stopped`; afterwards unused recorded tool or model lines are a mismatch note; the end matches when `code` is equal and, for `denied`, `denied_code` too. `exit_code` is 0 only when every step matches, nothing is left over, nothing stopped and the end matches.

- [ ] **Step 1: Write the failing tests**

Record with a traced `Env` dispatcher (Task 5), then replay on a second `Env` built the same way with a `ReplayClock`:

```python
async def test_same_code_replays_clean_on_a_fresh_state(tmp_path): ...
    # ids of project and round differ between the two Envs; the IdMap seeded from the first message
    # makes every step match; exit_code == 0
async def test_moving_clock_still_replays_clean(tmp_path): ...
    # record with a clock whose now() moves 0.001 per call; replay with ReplayClock; exit_code == 0
async def test_a_changed_handler_stops_at_its_step(tmp_path, monkeypatch): ...
    # monkeypatch validate_run_sheet's handler to deny; report.steps[-1].name == "validate_run_sheet",
    # same is False, exit_code == 1, stopped is set
async def test_keep_going_reports_every_mismatch(tmp_path, monkeypatch): ...
async def test_external_handlers_are_never_called(tmp_path): ...
    # the search tool's handler raises AssertionError if called; replay passes and the step is external
async def test_more_model_calls_than_recorded_is_a_mismatch(tmp_path): ...
async def test_budget_refusal_replays_as_the_same_refusal(tmp_path): ...    # exit_code == 0, end code denied
async def test_unconfigured_role_replays_as_the_same_refusal(tmp_path): ... # role_config None -> denied model_role
async def test_model_error_replays_as_model_unavailable(tmp_path): ...
async def test_newer_state_warns(tmp_path): ...                              # replay on the recording Env itself
async def test_incomplete_trace_exits_2(tmp_path): ...
def test_mask_ids_and_timestamp_tolerance():
    assert mask_ids("draft_" + "a" * 32) == "draft_*"
    rec = {"is_error": False, "content": '{"at": 1795000000.0}', "seconds": 0.2}
    assert same_result(rec, ToolOutcome(name="x", content='{"at": 1795000001.1}'), copy_dir="", data_dir="")
    assert not same_result(rec, ToolOutcome(name="x", content='{"at": 1795000002.0}'), copy_dir="", data_dir="")
```

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement `replay.py`** (split helpers so no function exceeds 50 lines).
- [ ] **Step 4: Run** — `.venv/bin/pytest tests/dispatch/test_replay.py -q`, expected: PASS.
- [ ] **Step 5: Commit** — `feat: replay a model trace against the current code`

---

### Task 8: Replay runtime and `growbridge trace replay`

**Files:**
- Create: `src/growbridge/replay_runtime.py`
- Modify: `src/growbridge/trace_cli.py` (add `replay`)
- Test: `tests/test_replay_runtime.py`, `tests/e2e/test_e2e_trace_replay.py`, `tests/test_trace_cli.py`

**Interfaces:**
- Consumes: Tasks 2, 3, 5 (`make_dispatcher` overrides), 7.
- Produces:
  - `class ReplaySource(Model)`: `path: Path`, `kind: Literal["option", "pre_run_copy", "config"]`, `reliable: bool` (`True` only for `pre_run_copy`)
  - `choose_source(trace_path: Path, trace: Trace, option: Path | None, settings: Settings) -> ReplaySource` — `option` first, then `trace_path.with_suffix(PRE_RUN_SUFFIX)` when `run["pre_run_copy"]` is set and the directory exists, then `settings.data_dir`
  - `build_replay_runtime(trace: Trace, settings: Settings, copy_dir: Path) -> tuple[Runtime, ReplayClock]` — `settings.model_copy(update={"data_dir": copy_dir, "model_trace": False, "backup_dir": None, "compute_templates_dir": None, "compute_member": None})`; `ReplayClock(run["at"], run["clock_synced"])`; `build_runtime(s, lambda _: SimulatedTransport(), clock, channels={}, heartbeats=None)`; never `start()`
  - `async def replay_file(trace_path: Path, settings: Settings, *, data_dir: Path | None = None, keep_going: bool = False, keep_copy: bool = False) -> tuple[ReplaySource, ReplayReport, Path | None]` — reads the trace (format error → a report with `exit_code=2`), chooses the source, `copy_data_dir` into `<tempdir>/data`, `relocate_paths(copy, run["data_dir"], str(copy))`, builds the runtime, calls `replay_trace` with `make=lambda c, b, r: make_dispatcher(runtime, c, private_dir(copy / "agent_work"), roles=r, budget=b, tracing=False)` and `copy_dir=str(copy)`; removes the temporary directory unless `keep_copy` (then returns its path)
  - `trace_cli`: `trace replay FILE [--data-dir DIR] [--keep-going] [--keep-copy]`; prints a first line naming the source and, when not reliable, `Replay from <kind>: results are for reference only (no pre-run copy).`; prints warnings, one line per step (`ok` / `DIFFERENT`), for the first mismatch the tool name, input, and a unified diff of the recorded and replayed results (indented JSON when both parse), then both end codes; returns `report.exit_code`

- [ ] **Step 1: Write the failing tests**

```python
def test_source_order(tmp_path, settings): ...                 # option > pre-run copy > config
async def test_existing_report_reads_on_the_copy(world): ...
    # a report published before the traced run; replaying an orchestrator read_artifact of it matches
async def test_end_to_end_replay_from_the_pre_run_copy_is_clean(world):
    # model_trace + pre_run_copies on; planner run as in test_e2e_agents; replay_file(trace, settings)
    # -> source.kind == "pre_run_copy", report.exit_code == 0, every step same
async def test_source_and_pre_run_copy_are_unchanged(world): ...   # sha256 of every file before == after
async def test_temporary_copy_is_removed_unless_keep_copy(world): ...  # path None and gone; with keep_copy the path exists
async def test_replay_runtime_is_never_started_and_has_no_outside_backends(world, monkeypatch): ...
    # Runtime.start raises if called; runtime.compute is None; no heartbeats; no channels
def test_cli_replay_exit_codes(tmp_path, ...): ...               # 0 clean, 1 after a monkeypatched handler, 2 for a cut-off file
```

- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement `replay_runtime.py` and the `replay` subcommand**
- [ ] **Step 4: Run** — `.venv/bin/pytest tests/test_replay_runtime.py tests/e2e/test_e2e_trace_replay.py tests/test_trace_cli.py -q`, expected: PASS.
- [ ] **Step 5: Commit** — `feat: replay a recorded run from the command line on a copy of the data`

---

### Task 9: Dev workbench `--trace`

**Files:**
- Modify: `scripts/dev_workbench.py:1-30` (module docstring), `:200-266` (remove `_clip`, `_role_of`, `_newest`, `RecordingClient`, `TRANSCRIPT_CHARS` when nothing else uses them), `:276-335` (`_run`), `:337-381` (`main`)
- Modify: `tests/test_dev_workbench_script.py:~100-130` (replace the `RecordingClient` test)

**Interfaces:**
- Consumes: `Settings.model_trace`, `Runtime.pre_run_copies` (Task 5).
- Produces: `--trace` flag. With `--trace` and no `--data-dir`, `main` prints `--trace needs --data-dir: the traces and pre-run copies must outlive the workbench` to stderr and returns 2. With both, `Settings(..., model_trace=True)` and, right after `build_runtime`, `runtime.pre_run_copies = True`; prints `Model traces: <data_dir>/model_traces`.

- [ ] **Step 1: Write the failing tests** — `test_trace_without_data_dir_is_refused`, `test_trace_turns_on_model_trace_and_pre_run_copies` (call `main` / `_run` the way the existing script tests do), and delete the old transcript test.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement; update the module docstring (`--transcript` paragraph replaced)**
- [ ] **Step 4: Run** — `.venv/bin/pytest tests/test_dev_workbench_script.py tests/test_demo_tools.py -q`, expected: PASS.
- [ ] **Step 5: Commit** — `feat: dev workbench --trace records runs with pre-run copies`

---

### Task 10: Documentation (en and zh-CN)

**Files (each in `docs/wiki/en/` and `docs/wiki/zh-CN/`):**
- `CLI-Reference.md`: `trace show` and `trace replay` (arguments, source order, exit codes, the "reference only" line).
- `Configuration-Reference.md`: `model_trace` (default off; cleartext prompts, web content and tool results; directory 0700 / files 0600; not in backups; never deleted automatically; turn it off after investigating).
- `Development-Setup-Testing-and-CI.md:130` and `Example-Full-Round-With-Claude.md:43`: `--transcript` → `--trace` with `--data-dir`; pre-run copies.
- `Troubleshooting-Runbook.md`: a section "A model run went wrong: use its trace" — turn on `model_trace`, find the file, `trace show`, `trace replay`, why a `serve` trace replays only for reference.
- `Data-Archive-and-Traceability.md`: traces and pre-run copies are not part of the archive and are not evidence.

- [ ] **Step 1: Write the English pages, then the Chinese pages with the same content and structure**
- [ ] **Step 2: Build the site** — `.venv/bin/python -m pip install -q -e '.[docs]'` once, then `.venv/bin/python scripts/build_wiki_site.py`; expected: exits 0 (no missing file, heading or sidebar entry).
- [ ] **Step 3: Run the docs tests** — `.venv/bin/pytest tests/docs -q`, expected: PASS.
- [ ] **Step 4: Commit** — `docs: model traces and replay in the wiki (en, zh-CN)`

---

### Final verification

- [ ] `.venv/bin/ruff check src tests scripts` and `.venv/bin/ruff format --check src tests scripts` — clean.
- [ ] `.venv/bin/pytest -q` — all pass; the count is the baseline 3926 plus the new tests, 1 skipped.
- [ ] `.venv/bin/python -m build` — builds.
- [ ] Manual check: `GROWBRIDGE_DEV_SECRET=… .venv/bin/python scripts/dev_workbench.py --data-dir <tmp> --trace --claude-code`, run one planning task, then `growbridge trace show` and `growbridge trace replay` on its trace (exit 0).
- [ ] Whole-branch review by a fresh reviewer against the spec.
