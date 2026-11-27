# 引导建立协议（第 1 块：不接模型的骨架）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户在工作台里按固定步骤（研究问题 → 作物 → 处理 → 测量 → 分析计划 → 规模 → 复核保存 → 轮次与目标）建好一份通过全部检查的协议；选项来自系统，每次选择都有记录。这一块不调用模型。

**Architecture:** 新包 `src/growbridge/guide/` 放纯函数（步骤答案、草稿推算、选项、组成协议）和一个只追加的会话存储；`workbench/guide.py` 加 8 条路由；工作台加 `guide` 页面。草稿在读取时由 `chosen` 事件推算。保存仍由操作员通过现有的 `POST /wb/protocols` 完成，之后引导记一条 `saved`。

**Tech Stack:** Python 3 / FastAPI / pydantic / SQLite（`archive/db.py` 的 `Database.migrate`）；原生 JS 工作台；pytest；`node --test`。

**Spec:** [`docs/superpowers/specs/2026-11-27-ai-guided-setup-design.md`](../specs/2026-11-27-ai-guided-setup-design.md)（§5.1–5.5、§5.9、§6、§9 第 1 块）。另外四块（接模型、人工施加的处理、目录提议、下一步卡）各有自己的计划，不在这里。

## Global Constraints

- 在从 `main` 新开的分支 `feat/guided-setup-skeleton` 上做（用 worktree）。第一个提交加入设计文档和本计划。
- 这一块不调用任何模型；页面文字不出现"AI"。
- 模型身份（`Actor.kind == "model"`）不能调用任何引导的写路由；保存协议照旧只走 `POST /wb/protocols`。
- 事件只追加：`GuideStore` 没有更新或删除的方法。草稿由 `chosen` 事件推算，没有可变的草稿行。
- 分配只由 `randomize_series` / `randomize_tents`（`planning/design.py:27,47`）生成；沿用旧版本时原样保留旧分配。
- 方法只有 `paired_block`、`two_group`；`max_missing_fraction` 默认 `0.2`，`max_deviation_fraction` 默认 `0.1`；`experimental_unit` 默认 `"tent"`。
- 同样的值，经引导组成的协议与手填表单建出的协议摘要相同。
- 选项来源只有 `system`、`own`、`carried` 三种。
- 新的拒绝原因按清单登记：`denial_codes.py`、`scripts/export_message_codes.py` 重新导出、`i18n/denials.{en,zh}.js` 文案。
- 新的 GET 路由进 `workbench/visibility.py` 的 `READ_RULES`；每条新路由进 `docs/wiki/{en,zh-CN}/API-Reference.md`，并更新那里的路由总数。
- i18n 中英键一一对应；文件不超过 800 行，函数少于 50 行；模型用不可变的 `growbridge.archive.models.Model`。
- 每个任务结束前跑：`ruff check src tests && ruff format --check src tests && pytest -q` 和 `node --test tests/web/*.test.mjs`；改过的 JS 文件跑 `node --check`。

## Review Focus

1. **沿用一个分配是手填的旧协议。** 旧版本的分配不是种子生成的（表单允许手填），重新随机就会悄悄换掉分配。期望：原样保留旧分配。测试在 Task 2（`test_carried_scale_keeps_hand_written_allocations`）和 Task 4。
2. **规模答案组不出协议。** 比如帐篷数不是处理数的倍数，`randomize_tents` 会抛 `ValueError`。期望：复核列出问题，不是 500。测试在 Task 4（`test_review_reports_a_layout_that_cannot_be_randomized`）。
3. **两个标签页同时提交同一步。** 期望：序号不重复，后提交的那次生效。测试在 Task 1（`test_concurrent_appends_get_distinct_numbers`）。
4. **报告保存了一份不属于本会话项目的协议，或者不存在的版本。** 期望：拒绝，什么都不记。测试在 Task 5（`test_saved_refuses_a_protocol_of_another_project`）。
5. **目录在选择之后、复核之前变了**（例如变量被弃用）。期望：复核列出 `check_protocol` 的问题，页面照常显示。测试在 Task 4（`test_review_lists_catalog_problems_instead_of_failing`）。

---

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `src/growbridge/guide/__init__.py` | 空 |
| `src/growbridge/guide/store.py` | `GuideStore`：两张表，会话和只追加的事件 |
| `src/growbridge/guide/steps.py` | 步骤 ID、顺序、依赖、每步的答案模型、答案检查 |
| `src/growbridge/guide/draft.py` | 由事件推算草稿和步骤状态；从已有协议推出沿用的答案 |
| `src/growbridge/guide/crops.py` | 核实过的作物表 |
| `src/growbridge/guide/options.py` | 每一步的系统选项 |
| `src/growbridge/guide/compose.py` | 组成协议、协议 ID 和版本、复核、找出保存前被改过的字段 |
| `src/growbridge/workbench/guide.py` | `add_guide_routes` |
| `src/growbridge/web/workbench/pages/guide.js` | 引导页：步骤栏、当前步骤、草稿摘要 |
| `src/growbridge/web/workbench/pages/guide-steps.js` | 第 1–6 步的步骤卡 |
| `src/growbridge/web/workbench/pages/guide-review.js` | 第 7 步复核保存、第 8 步轮次与目标 |
| `src/growbridge/web/workbench/guide-draft.js` | 协议对象 → 协议表单的草稿（纯函数） |
| `src/growbridge/web/workbench/i18n/guide.{en,zh}.js` | 引导的文案 |
| 修改：`workbench/api.py`、`runtime.py`、`workbench/visibility.py`、`denial_codes.py`、`web/workbench/router.js`、`main.js`、`i18n/{en,zh}.js`、`pages/projects.js`、`pages/project.js`、`tests/workbench/workbench_support.py`、`tests/web/support/render-page.mjs`、`tests/web/leaks.test.mjs` | 接线 |

---

### Task 1: 引导会话存储

**Files:**
- Create: `src/growbridge/guide/__init__.py`, `src/growbridge/guide/store.py`
- Test: `tests/guide/test_guide_store.py`

**Interfaces:**
- Produces:
  - `NAMESPACE = "guide"`
  - `EventKind = Literal["offered", "suggested", "chosen", "reopened", "saved"]`
  - `class GuideSession(Model)`: `session_id: str, project_id: str, operator: str, started_at: float, lang: Literal["en", "zh"], seed: int`
  - `class GuideEvent(Model)`: `session_id: str, seq: int, step: str, kind: EventKind, payload: dict[str, Any], actor: str, at: float`
  - `class GuideStore`:
    - `__init__(self, db: Database, clock: Clock) -> None`
    - `start(self, project_id: str, operator: str, lang: Literal["en", "zh"]) -> GuideSession`
    - `session(self, session_id: str) -> GuideSession | None`
    - `append(self, session_id: str, step: str, kind: EventKind, payload: dict[str, Any], actor: str) -> GuideEvent`
    - `append_many(self, session_id: str, items: Sequence[tuple[str, EventKind, dict[str, Any]]], actor: str) -> tuple[GuideEvent, ...]`
    - `events(self, session_id: str) -> tuple[GuideEvent, ...]`（按 `seq` 升序）

- [ ] **Step 1: 写失败的测试**

```python
def test_a_session_gets_an_id_a_seed_and_no_events(store):
    s = store.start("project-1", "alice", "zh")
    assert s.session_id.startswith("guide-") and 1 <= s.seed < 2**31
    assert store.session(s.session_id) == s
    assert store.events(s.session_id) == ()

def test_events_are_numbered_in_order_and_kept_as_written(store):
    s = store.start("project-1", "alice", "zh")
    first = store.append(s.session_id, "question", "chosen", {"answer": {"question": "Q"}}, "alice")
    store.append_many(s.session_id, [("crop", "offered", {"options": []}), ("crop", "chosen", {"answer": {}})], "alice")
    events = store.events(s.session_id)
    assert [e.seq for e in events] == [1, 2, 3]
    assert [e.kind for e in events] == ["chosen", "offered", "chosen"]
    assert events[0] == first

def test_an_unknown_session_takes_no_event(store):
    assert store.session("guide-nope") is None
    with pytest.raises(KeyError):
        store.append("guide-nope", "question", "chosen", {}, "alice")

def test_concurrent_appends_get_distinct_numbers(tmp_path):
    # 两个 GuideStore 共用一个数据库文件，交替写入；序号 1..N 不重复
```

`store` fixture：`GuideStore(Database(tmp_path / "guide.db"), FakeClock(1000.0))`（用工作台 bench 用的那个 `FakeClock`）。

- [ ] **Step 2: 跑测试，确认失败**

Run: `pytest tests/guide/test_guide_store.py -v`
Expected: FAIL（`ModuleNotFoundError: growbridge.guide`）

- [ ] **Step 3: 实现 `GuideStore`**

照 `observer/device_notes.py` 和 `archive/evidence_ledger.py` 的写法：`STEPS` 里两条建表语句。`guide_sessions(session_id TEXT PRIMARY KEY, project_id, operator, started_at REAL, lang, seed INTEGER)`；`guide_events(session_id REFERENCES guide_sessions, seq INTEGER, step, kind, payload TEXT, actor, at REAL, PRIMARY KEY (session_id, seq))`，再加一个按 `session_id` 的索引。`session_id = "guide-" + secrets.token_hex(8)`，`seed = secrets.randbelow(2**31 - 1) + 1`。`payload` 用 canonical JSON 存。序号在 `with db.transaction():` 里取 `COALESCE(MAX(seq), 0) + 1`；`append_many` 在同一个事务里写完全部。

- [ ] **Step 4: 跑测试，确认通过**

Run: `pytest tests/guide/test_guide_store.py -v` → PASS

- [ ] **Step 5: 提交**

```bash
git add src/growbridge/guide tests/guide
git commit -m "feat: guide sessions keep an append-only record of each step"
```

---

### Task 2: 步骤、答案、草稿和沿用

**Files:**
- Create: `src/growbridge/guide/steps.py`, `src/growbridge/guide/draft.py`
- Test: `tests/guide/test_guide_steps.py`, `tests/guide/test_guide_draft.py`

**Interfaces:**
- Consumes: `GuideEvent`（Task 1）；`Catalog`（`vocab/catalog.py:64`）；`taxon_problems`（`vocab/curie.py:45`）；`Treatment`、`Allocation`、`ResearchProtocol`（`archive/models.py`）。
- Produces（`steps.py`）：
  - `StepId = Literal["question", "crop", "treatments", "measures", "analysis", "scale", "review", "round"]`
  - `STEPS: tuple[StepId, ...]`（上面的顺序）；`ANSWERED: tuple[StepId, ...] = STEPS[:6]`
  - `DEPENDS_ON: Mapping[StepId, frozenset[StepId]] = {"analysis": {"treatments", "measures"}, "scale": {"treatments", "analysis"}}`
  - 答案模型（都是 `Model`）：
    - `QuestionAnswer(question: str 1..2000, hypothesis: str = "" ≤2000)`
    - `CropAnswer(crop: str ≤200, crop_taxon: str, cultivar: str = "", batch: str = "")`
    - `TreatmentsAnswer(treatments: tuple[Treatment, ...] 至少 2 个, control_treatment_id: str)`
    - `MeasuresAnswer(variables: tuple[str, ...] 至少 1 个, primary_endpoint: str)`
    - `AnalysisAnswer(target_effect: float, method: Literal["paired_block", "two_group"], exclusion_rules: tuple[str, ...] = (), max_missing_fraction: float = 0.2, max_deviation_fraction: float = 0.1)`，两个比例在 0..1
    - `ScaleAnswer(layout: Literal["series", "tents"], units: tuple[str, ...] 至少 1 个, blocks: int | None = None, rounds: int | None = None, stages: tuple[str, ...] 至少 1 个, experimental_unit: str = "tent", randomization_seed: int | None = None, allocations: tuple[Allocation, ...] | None = None)`。`series` 必须给 `blocks`、`units` 只有一个；`tents` 必须给 `rounds`。`randomization_seed` 和 `allocations` 只在沿用旧版本时出现。
  - `ANSWER_MODELS: Mapping[StepId, type[Model]]`（6 个有答案的步骤）
  - `parse_answer(step: StepId, raw: Mapping[str, Any]) -> Model`，不合格时抛 `ValueError`
  - `answer_problems(step: StepId, answer: Model, catalog: Catalog) -> tuple[str, ...]`。规则与 `vocab/checks.py` 一致：处理的因子键必须是目录里 `kind == "factor"` 的现行 ID；处理 ID 不重复；对照在处理里；变量是现行 ID（不是别名、没弃用）、不重复；主要终点是 `manual` 并在变量里；`crop_taxon` 过 `taxon_problems`。
- Produces（`draft.py`）：
  - `Source = Literal["system", "own", "carried"]`
  - `class Chosen(Model)`: `step: StepId, answer: dict[str, Any], source: Source, option_ids: tuple[str, ...], seq: int`
  - `class StepState(Model)`: `step: StepId, status: Literal["pending", "done", "needs_review"], chosen: Chosen | None`
  - `chosen` 事件的 `payload` 固定为 `{"answer": dict, "source": Source, "option_ids": list[str]}`；`offered` 是 `{"options": [Option…]}`；`reopened` 是 `{}`；`saved` 是 `{"protocol_id", "version", "digest", "edited": list[str]}`
  - `latest_chosen(events: Sequence[GuideEvent]) -> dict[StepId, Chosen]`（每步取 `seq` 最大的 `chosen`）
  - `step_states(events: Sequence[GuideEvent]) -> tuple[StepState, ...]`（`ANSWERED` 的 6 步）。`DEPENDS_ON` 里任何一步的最新选择比自己新，状态就是 `needs_review`，并且沿依赖传递。
  - `carried_answers(protocol: ResearchProtocol) -> dict[StepId, dict[str, Any]]`

- [ ] **Step 1: 写失败的测试**

```python
def test_a_treatment_factor_must_be_a_catalog_factor():
    answer = parse_answer("treatments", {"treatments": [t("a", {"light": 40}), t("b", {"nutrient": 2})], "control_treatment_id": "a"})
    assert any("nutrient" in p for p in answer_problems("treatments", answer, TEST_CATALOG))

def test_the_control_must_be_one_of_the_treatments(): ...      # control_treatment_id="z" → 有问题
def test_treatment_ids_are_not_repeated(): ...                  # 两个 "a" → 有问题
def test_the_primary_endpoint_must_be_a_listed_manual_variable(): ...  # 传感器变量做终点 → 有问题
def test_a_malformed_species_is_a_problem(): ...                # crop_taxon="4236" → 有问题
def test_series_needs_blocks_and_one_unit():
    with pytest.raises(ValueError):
        parse_answer("scale", {"layout": "series", "units": ["tent-1", "tent-2"], "blocks": 2, "stages": ["vegetative"]})

def test_the_latest_choice_of_a_step_wins(): ...
def test_changing_treatments_after_analysis_marks_analysis_and_scale_for_review():
    states = {s.step: s.status for s in step_states(events_choosing("treatments", "measures", "analysis", "scale", "treatments"))}
    assert states["analysis"] == "needs_review" and states["scale"] == "needs_review"
    assert states["measures"] == "done"

def test_carried_answers_reproduce_the_example_protocol_as_a_series():
    carried = carried_answers(make_protocol())
    assert carried["scale"]["layout"] == "series" and carried["scale"]["blocks"] == 2
    assert carried["scale"]["allocations"] is None      # 种子 20261118 能重现这些分配

def test_carried_scale_keeps_hand_written_allocations():
    p = make_protocol(allocations=<和种子不符的 4 条>)
    assert carried_answers(p)["scale"]["allocations"] == [a.model_dump(mode="json") for a in p.allocations]
```

（`t(id, factors)` 是测试里的小帮手，返回一个 `Treatment` 的 dict；`events_choosing(*steps)` 按顺序为每步造一条合法的 `chosen` 事件。）

- [ ] **Step 2: 跑测试，确认失败**

Run: `pytest tests/guide/test_guide_steps.py tests/guide/test_guide_draft.py -v` → FAIL（导入失败）

- [ ] **Step 3: 实现 `steps.py` 和 `draft.py`**

`carried_answers` 判断布局的办法：所有分配用同一个单位，就是 `series`（`blocks` 取协议的 `blocks`）；否则是 `tents`（`units` 按首次出现的顺序排，`rounds` 取协议的 `rounds`）。然后用协议的种子跑对应的随机函数：结果和协议的分配完全相同，`allocations` 就是 `None`；不同，就原样保存旧分配。`randomization_seed` 总是写协议的种子。

- [ ] **Step 4: 跑测试，确认通过** → PASS

- [ ] **Step 5: 提交**

```bash
git add src/growbridge/guide tests/guide
git commit -m "feat: guide steps, their answers, and the draft worked out from choices"
```

---

### Task 3: 作物表和每一步的系统选项

**Files:**
- Create: `src/growbridge/guide/crops.py`, `src/growbridge/guide/options.py`
- Test: `tests/guide/test_guide_options.py`

**Interfaces:**
- Consumes: `StepId`、`Chosen`（Task 2）；`Catalog`。
- Produces:
  - `class Crop(Model)`: `key: str, label_en: str, label_zh: str, scientific_name: str, taxon: str`
  - `CROPS: tuple[Crop, ...]`；`CHECKED_ON: str`（核实日期，ISO 格式）
  - `class Option(Model)`: `id: str, value: dict[str, Any], label_en: str, label_zh: str`
  - `class StepOptions(Model)`: `step: StepId, options: tuple[Option, ...], defaults: dict[str, Any]`
  - `options_for(step: StepId, catalog: Catalog, seed: int) -> StepOptions`

每一步的选项：

| 步 | `options` | `defaults` |
| --- | --- | --- |
| question | 无 | 无 |
| crop | `CROPS` 每项一个：`id = key`，`value = {"crop": label_en, "crop_taxon": taxon}` | 无 |
| treatments | 目录里每个没弃用的 `factor`：`id = 变量 ID`，`value = {"factor": id, "unit": unit}` | 无 |
| measures | 目录里每个没弃用的 `sensor` 和 `manual`：`value = {"variable": id, "kind": kind, "unit": unit}` | 无 |
| analysis | `paired_block`、`two_group` 各一个：`value = {"method": ...}` | `{"max_missing_fraction": 0.2, "max_deviation_fraction": 0.1}` |
| scale | `series`、`tents` 各一个：`value = {"layout": ...}` | `{"randomization_seed": seed, "experimental_unit": "tent"}` |
| review、round | 无 | 无 |

作物表的初始内容：生菜 *Lactuca sativa*、番茄 *Solanum lycopersicum*、黄瓜 *Cucumis sativus*、辣椒 *Capsicum annuum*、草莓 *Fragaria × ananassa*、菠菜 *Spinacia oleracea*、罗勒 *Ocimum basilicum*、拟南芥 *Arabidopsis thaliana*。**实现者逐个在 NCBI Taxonomy 网页上查出编号，确认等级是 species，再写进去，并把 `CHECKED_ON` 设为查询当天。** 不要凭记忆写编号。

- [ ] **Step 1: 写失败的测试**

```python
def test_every_crop_has_a_well_formed_species_and_a_unique_key():
    assert all(taxon_problems(c.taxon, "") == [] for c in CROPS)
    assert len({c.key for c in CROPS}) == len(CROPS)
    assert date.fromisoformat(CHECKED_ON)

def test_treatment_options_are_the_catalog_factors_that_are_not_deprecated():
    ids = {o.id for o in options_for("treatments", TEST_CATALOG, 7).options}
    assert ids == {v.id for v in TEST_CATALOG.variables if v.kind == "factor" and not v.deprecated}

def test_measure_options_leave_out_factors(): ...
def test_analysis_offers_two_methods_and_the_default_thresholds():
    o = options_for("analysis", TEST_CATALOG, 7)
    assert [x.id for x in o.options] == ["paired_block", "two_group"]
    assert o.defaults == {"max_missing_fraction": 0.2, "max_deviation_fraction": 0.1}

def test_scale_offers_the_session_seed(): assert options_for("scale", TEST_CATALOG, 42).defaults["randomization_seed"] == 42
```

- [ ] **Step 2: 跑测试，确认失败** → FAIL
- [ ] **Step 3: 实现 `crops.py` 和 `options.py`**（选项是纯函数，同样的输入永远给出同样的选项和顺序）
- [ ] **Step 4: 跑测试，确认通过** → PASS
- [ ] **Step 5: 提交** `git commit -m "feat: guide options come from the catalog, a checked crop table and fixed lists"`

---

### Task 4: 组成协议与复核

**Files:**
- Create: `src/growbridge/guide/compose.py`
- Test: `tests/guide/test_guide_compose.py`

**Interfaces:**
- Consumes: `Chosen`、`StepId`、`ANSWERED`、`parse_answer`（Task 2）；`randomize_series`、`randomize_tents`、`check_experimental_design`；`checked_protocol`（`workbench/rounds.py:237`）；`check_protocol`、`taxon_problems`；`content_digest`。
- Produces:
  - `class IncompleteDraft(ValueError)`，带 `missing: tuple[StepId, ...]`
  - `compose(answers: Mapping[StepId, Chosen], *, project_id: str, protocol_id: str, version: int, seed: int) -> ResearchProtocol`
  - `new_protocol_id(project_id: str, taken: Sequence[str], count: int) -> str`：和 `protocol-form.js` 的 `newProtocolId` 一致，即 `protocol-{n}-{project_id[-6:]}`，`n` 从 `count + 1` 往上找第一个没被占用的
  - `next_version(versions: Sequence[int]) -> int`：没有版本时是 1，否则最大值加 1
  - `class Review(Model)`: `protocol: ResearchProtocol | None, missing: tuple[StepId, ...], problems: tuple[str, ...], design: tuple[Finding, ...], ready: bool`
  - `review(answers, *, project_id, protocol_id, version, seed, catalog, declared_before: frozenset[str]) -> Review`。`ready` 的条件：没有缺的步骤、没有问题、没有阻断性的设计结果。
  - `edited_fields(composed: ResearchProtocol, saved: ResearchProtocol) -> tuple[str, ...]`：顶层字段名，`analysis` 里的字段写成 `analysis.<名字>`；按字母排序。

组成规则：`series` → `allocations = randomize_series(处理 ID, blocks, seed, units[0])`，`rounds = blocks × 处理数`；`tents` → `allocations = randomize_tents(处理 ID, units, rounds, seed)`，`blocks = rounds`。答案里有 `randomization_seed` 就用它，没有就用会话的种子。答案里有 `allocations` 就原样使用。`variables`、`analysis`、其余字段直接来自对应的答案。

- [ ] **Step 1: 写失败的测试**

```python
def test_composing_the_carried_example_gives_back_the_same_protocol():
    p = make_protocol()
    composed = compose(chosen_from(carried_answers(p)), project_id=p.project_id, protocol_id=p.id, version=p.version, seed=1)
    assert content_digest(composed) == content_digest(p)

def test_a_series_has_blocks_times_treatments_rounds(): ...
def test_tents_use_one_block_per_round(): ...   # 4 个帐篷、2 个处理、3 轮 → allocations == randomize_tents(...)，blocks == 3
def test_a_missing_step_is_named():
    with pytest.raises(IncompleteDraft) as e: compose({...缺 scale...}, ...)
    assert e.value.missing == ("scale",)

def test_new_protocol_ids_match_the_web_form():
    assert new_protocol_id("project-abcdef123456", taken=[], count=0) == "protocol-1-123456"
    assert new_protocol_id("project-abcdef123456", taken=["protocol-2-123456"], count=1) == "protocol-3-123456"

def test_review_is_ready_for_a_complete_valid_draft(): ...
def test_review_lists_catalog_problems_instead_of_failing():   # 变量在目录里已弃用
    r = review(..., catalog=<把该变量标为 deprecated 的目录>, declared_before=frozenset())
    assert not r.ready and r.problems

def test_review_reports_a_layout_that_cannot_be_randomized():   # 3 个帐篷、2 个处理
    r = review(...)
    assert not r.ready and r.protocol is None and r.problems

def test_edited_fields_name_what_changed():
    assert edited_fields(p, p.model_copy(update={"question": "other"})) == ("question",)
    changed = p.model_copy(update={"analysis": p.analysis.model_copy(update={"target_effect": 0.3})})
    assert edited_fields(p, changed) == ("analysis.target_effect",)
```

- [ ] **Step 2: 跑测试，确认失败** → FAIL
- [ ] **Step 3: 实现 `compose.py`**（`review` 把 `IncompleteDraft`、随机函数抛出的 `ValueError`、`checked_protocol` 的拒绝都接住，转成 `missing` 或 `problems`）
- [ ] **Step 4: 跑测试，确认通过** → PASS
- [ ] **Step 5: 提交** `git commit -m "feat: the guide composes a protocol from its draft and reviews it with the save checks"`

---

### Task 5: 路由和接线

**Files:**
- Create: `src/growbridge/workbench/guide.py`
- Modify: `src/growbridge/workbench/api.py`（`create_workbench`、`Workbench.__init__` 加 `guide: GuideStore | None = None`，在 `:292` 附近调用 `add_guide_routes`）；`src/growbridge/runtime.py`（`build_runtime` 里 `guide=GuideStore(dbs["workflow"], clock)`，`Runtime` 加字段 `guide: GuideStore | None = None`，`Runtime.workbench()` 的 `extra` 里传下去，照 `notes` 的接法 `:233,:280-285,:689`）；`src/growbridge/workbench/visibility.py`（`READ_RULES`）；`src/growbridge/denial_codes.py`；`tests/workbench/workbench_support.py`（`Bench` 建一个 `GuideStore` 并传入，再暴露为 `bench.guide`）；`docs/wiki/{en,zh-CN}/API-Reference.md`
- Modify: `src/growbridge/web/workbench/i18n/denials.{en,zh}.js`、`tests/web/fixtures/message-codes.json`（用脚本重新生成）
- Test: `tests/workbench/test_workbench_guide.py`

**Interfaces:**
- Consumes: Task 1–4 的全部；`scope.project_write` / `project_read`（`workbench/scope.py:15,41`）；`denials.unknown`；`rejected`（`workbench/common.py:16`）；`not_found`（`api.py:171`）；`estimate_sample_size`。
- Produces：`add_guide_routes(router: APIRouter, operator: Dependency, workflow: WorkflowService, guide: GuideStore, access: Access | None = None) -> None`，加下面 8 条路由（都在 `/wb` 下）：

| 方法和路径 | 请求体 / 参数 | 回答 |
| --- | --- | --- |
| `POST /guide/sessions` | `GuideStartIn{project_id: Ident, lang: Literal["en","zh"] = "zh"}` | `{"session_id"}`。项目已有协议时，从最近保存的版本为 6 步各写一条 `chosen`，来源是 `carried`。 |
| `GET /guide/sessions/{session_id}` | — | `SessionView`：`{session, steps: [StepState…], saved: [{protocol_id, version, digest, edited}]}` |
| `GET /guide/sessions/{session_id}/steps/{step}` | — | `StepOptions` |
| `POST /guide/sessions/{session_id}/steps/{step}/choose` | `ChooseIn{answer: dict, option_ids: tuple[str, ...] = ()}` | `SessionView`。在一个事务里先记 `offered`（服务器重新算出的选项），再记 `chosen`（来源：有 `option_ids` 就是 `system`，没有就是 `own`）。 |
| `POST /guide/sessions/{session_id}/steps/{step}/reopen` | — | `SessionView`，记一条 `reopened` |
| `GET /guide/sessions/{session_id}/review` | — | `Review`，外加算好的 `protocol_id`、`version` |
| `GET /guide/sample-size` | `effect: float, sd: float, design: Literal["paired_block","two_group"]` | `{"n", "design"}`：`paired_block` 时 `n` 是区组数，`two_group` 时是每组的单位数（`estimate_sample_size` 的定义） |
| `POST /guide/sessions/{session_id}/saved` | `SavedIn{protocol_id: Ident, version: int}` | `SessionView`，记一条 `saved`，带上 `digest` 和 `edited_fields` |

规则：
- 会话不存在，或者调用者看不到它的项目：`not_found`。写操作先过 `project_write`；会话的 `operator` 不是调用者时，抛 `Denied("state", ..., reason="guide_not_owner")`。
- `step` 不在 `STEPS` 里：422。答案解析失败、有 `answer_problems`、`option_ids` 不在重新算出的选项里：`rejected(..., reason="guide_answer_invalid", params={"step": step})`。
- `saved`：协议用 `workflow.store.protocol(protocol_id, version)` 读回来；不存在或 `project_id` 不是会话的项目，按 `denials.unknown("protocol", ...)` 拒绝，什么都不记。
- `review` 的 `protocol_id`、`version`：有沿用的版本，就用它的 ID 和下一个版本号；没有，就用 `new_protocol_id`。`declared_before` 用 `workflow.store.protocol_variables_before`。
- 模型身份：所有写路由都要求 `Actor.kind == "operator"`，照现有 `operator` 依赖的写法。

新的拒绝原因（`denial_codes.py`）：
- `_register("state", ("guide_not_owner", ()), action=False)`。中文："这份引导是另一位操作员开始的，只有他们能修改。" 英文："Another operator started this guide; only they can change it."
- `_register("param", ("guide_answer_invalid", ("step",)))`。中文："这一步的答案不符合要求。" `.action`："按提示改好这一步，再提交。" 英文："This step's answer is not acceptable." / "Fix this step as shown and submit it again." 文案里不用占位符。

- [ ] **Step 1: 写失败的测试**

```python
def test_a_new_session_has_six_pending_steps(bench, operator):
    pid = new_project(bench, operator)
    sid = bench.post(operator, "/wb/guide/sessions", {"project_id": pid}).json()["session_id"]
    view = operator.get(f"/wb/guide/sessions/{sid}").json()
    assert [s["status"] for s in view["steps"]] == ["pending"] * 6

def test_choosing_an_offered_crop_records_offer_and_choice(bench, operator):
    ...choose crop with option_ids=["lettuce"]...
    kinds = [e.kind for e in bench.guide.events(sid)]
    assert kinds[-2:] == ["offered", "chosen"] and bench.guide.events(sid)[-1].payload["source"] == "system"

def test_an_unknown_factor_is_refused_with_the_step(bench, operator):
    r = choose(bench, operator, sid, "treatments", {... "nutrient" ...})
    assert r.status_code == 422 and detail(r)["reason"] == "guide_answer_invalid" and detail(r)["params"] == {"step": "treatments"}

def test_an_option_that_was_not_offered_is_refused(bench, operator): ...
def test_another_operator_cannot_change_the_session(tmp_path): ...   # Bench.full，第二个操作员也有项目权限 → 409 guide_not_owner
def test_a_complete_draft_reviews_ready_and_saves_through_the_normal_route(bench, operator):
    review = operator.get(f"/wb/guide/sessions/{sid}/review").json()
    assert review["ready"] is True
    saved = bench.post(operator, "/wb/protocols", {"protocol": review["protocol"]})
    assert saved.status_code == 200
    view = bench.post(operator, f"/wb/guide/sessions/{sid}/saved", {"protocol_id": review["protocol_id"], "version": review["version"]}).json()
    assert view["saved"][0]["edited"] == [] and view["saved"][0]["digest"] == saved.json()["digest"]

def test_editing_the_question_in_the_form_is_recorded(bench, operator): ...   # 保存前改 question → edited == ["question"]
def test_saved_refuses_a_protocol_of_another_project(bench, operator): ...    # 拒绝，事件数不变
def test_a_project_with_a_protocol_starts_from_it(bench, operator):
    # 先保存 make_protocol(project_id=pid)，再开会话：6 步都是 done、来源 carried；review 的 version == 2，且协议 ID 不变
def test_sample_size_matches_the_design_helper(operator):
    r = operator.get("/wb/guide/sample-size", params={"effect": 0.15, "sd": 0.1, "design": "paired_block"}).json()
    assert r["n"] == estimate_sample_size(0.15, 0.1)
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `pytest tests/workbench/test_workbench_guide.py -v` → FAIL（404）

- [ ] **Step 3: 实现路由，完成接线和登记**

`PYTHONPATH=src python scripts/export_message_codes.py` 重新导出 `tests/web/fixtures/message-codes.json`。在 `docs/wiki/en/API-Reference.md` 和 `docs/wiki/zh-CN/API-Reference.md` 加一节"引导"（每条路由一行），并更新路由总数那句话。

- [ ] **Step 4: 跑全部测试，确认通过**

Run: `pytest -q && node --test tests/web/*.test.mjs`
Expected: 全部 PASS。`test_denial_codes.py`、`test_message_codes.py`、`test_workbench_multi_user_reads.py`、`tests/docs/test_docs_routes.py`、`tests/web/messages.test.mjs` 都要过。

- [ ] **Step 5: 提交** `git commit -m "feat: guide routes, from a new session to the saved protocol"`

---

### Task 6: 引导页（步骤栏、第 1–6 步、草稿摘要）

**Files:**
- Create: `src/growbridge/web/workbench/pages/guide.js`, `src/growbridge/web/workbench/pages/guide-steps.js`, `src/growbridge/web/workbench/i18n/guide.en.js`, `src/growbridge/web/workbench/i18n/guide.zh.js`, `tests/web/fixtures/guide-session.json`, `tests/web/fixtures/guide-options-crop.json`
- Modify: `router.js`（`WITH_ID` 加 `guide: ["guide", "sessionId"]`，`PAGES` 加 `"guide"`）；`main.js`（`ID_CRUMBS` 加引导）；`i18n/en.js`、`i18n/zh.js`（展开 `guide` 子表）；`tests/web/support/render-page.mjs`（`ROUTES` 里加两个 GET）；fixtures 的 README 表；`tests/web/leaks.test.mjs`（`PAGES_CHECKED` 加 `guide`）
- Test: `tests/web/guide-page.test.mjs`

**Interfaces:**
- Consumes: Task 5 的路由和回答形状。
- Produces：
  - `pages/guide.js`：`export async function render(ctx, { sessionId })`，返回 `{ element, refresh }`
  - `pages/guide-steps.js`：`export function stepCard(ctx, { session, step, options, onChosen })`，返回一个元素；提交时调用 `ctx.api.post(\`/guide/sessions/${id}/steps/${step}/choose\`, { answer, option_ids })`，成功后调用 `onChosen(view)`
  - i18n 键前缀 `guide.*`。步骤标题（`guide.step.<id>`）的中文：项目、研究问题、作物、处理、测量、分析计划、规模、复核保存、轮次与目标；英文：Project、Research question、Crop、Treatments、Measurements、Analysis plan、Scale、Review and save、Round and goal。来源标记（`guide.source.<s>`）的中文：系统选项、自己填写、沿用上一版；英文：From the list、Your own、Kept from the last version。状态（`guide.status.needs_review`）的中文："前面改过，请重看"；英文："An earlier step changed; please check this one"。

页面行为：
- 左边步骤栏有 9 项（0–8）。第 0 步总是已完成；当前步骤是第一个 `pending` 或 `needs_review` 的步骤；全部完成后是 `review`。点任何已完成的步骤会打开那一步，并 `POST .../reopen`。
- 中间是当前步骤的卡片，选项来自 `GET .../steps/{step}`：
  - question：两个文本框；
  - crop：作物单选（标签按界面语言取 `label_zh` / `label_en`），外加"表里没有"，展开后手填物种名和 `NCBITaxon:` 编号，旁边是 NCBI Taxonomy 的查询链接（`https://www.ncbi.nlm.nih.gov/taxonomy`，新标签页打开）；
  - treatments：因子单选，处理行（ID、名称、档位），对照单选；
  - measures：变量多选，主要终点从已选的 `manual` 变量里单选；
  - analysis：方法单选（各附一句中英说明）、目标效应、排除规则（每行一条）、两个比例（预填默认值）；
  - scale：布局单选（`series` 一个帐篷轮换，`tents` 多个帐篷同时），区组数或轮数，单位名，阶段名（每行一个），种子（只读显示）。另有"估算区组数"：填标准差，调用 `GET /guide/sample-size`，把结果填进区组数；"不知道"按钮填 2，并显示提示"按先导实验处理，结论会是不确定"。选定规模后，页面读一次 `GET .../review`；`design` 里有阻断性结果时，留在规模这一步并列出这些结果（规格 §5.1："有阻断项就停在这一步"）。
- 右边草稿摘要：每个已答步骤一行，带来源标记。
- 拒绝照现有页面的方式显示（`errorBox`、`showErrors`）。

- [ ] **Step 1: 写失败的测试**

```js
test("the rail shows nine steps and opens the first pending one", async () => {
  const { element } = await renderPage("guide", { sessionId: "guide-1" }, { lang: "zh" });
  assert.equal(railItems(element).length, 9);
  assert.equal(currentTitle(element), "研究问题");
});
test("choosing a listed crop sends its option id", async () => { /* 断言 api.calls 里的 choose 请求体：option_ids == ["lettuce"]，answer.crop_taxon 是 fixture 里的编号 */ });
test("a step to recheck says so", async () => { /* fixture 中 analysis 为 needs_review → 文本含"前面改过，请重看" */ });
test("the draft panel marks where each answer came from", async () => { /* 依次出现"自己填写""系统选项""沿用上一版" */ });
test("the sample-size helper fills the blocks", async () => { /* answers["/guide/sample-size?..."] 回 {n: 6} → 区组数输入框的值是 "6" */ });
test("a blocking design finding keeps the page on the scale step", async () => { /* choose scale 成功，review fixture 的 design 有 blocking → 当前步骤仍是"规模"，并显示该结果 */ });
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `node --test tests/web/guide-page.test.mjs` → FAIL

- [ ] **Step 3: 实现页面、文案、路由登记和测试支持**
- [ ] **Step 4: 跑测试，确认通过**

Run: `node --test tests/web/*.test.mjs && for f in src/growbridge/web/workbench/pages/guide*.js src/growbridge/web/workbench/i18n/guide.*.js; do node --check "$f"; done` → PASS

- [ ] **Step 5: 提交** `git commit -m "feat: the guide page walks through the six answer steps"`

---

### Task 7: 复核保存（第 7 步）

**Files:**
- Create: `src/growbridge/web/workbench/guide-draft.js`, `src/growbridge/web/workbench/pages/guide-review.js`, `tests/web/fixtures/guide-review.json`
- Modify: `pages/guide.js`（`review` 步交给 `reviewStep`）；`tests/web/support/render-page.mjs`（`ROUTES` 加 `/guide/sessions/guide-1/review`）
- Test: `tests/web/guide-review.test.mjs`

**Interfaces:**
- Consumes: `protocolForm`、`buildProtocol`（`pages/protocol-form.js:246,138`）；`saveDraft`（`drafts.js`）；Task 5 的 `review`、`saved` 路由。
- Produces：
  - `guide-draft.js`：`export function protocolFormDraft(protocol, { saveAs })`，返回 `{ fields, parts }`，所有值都是文本，形状见 `ui/forms.js:343-347`。行字段用 `"\n"` 连接；`factors` 写成每行一个 `key=value`；`saveAs` 是沿用时的协议 ID，新协议时是 `""`。
  - `pages/guide-review.js`：`export async function reviewStep(ctx, { session, project, onSaved })`

页面行为：
- 读 `GET .../review`。`missing` 列成"还没答的步骤"（可以点过去）；`problems` 和阻断性的 `design` 结果列成"保存前要解决的问题"；不阻断的设计结果列为提示。
- `review.protocol` 存在时，先 `saveDraft(\`protocol:${pid}-form\`, protocolFormDraft(review.protocol, { saveAs }))`，再挂上 `protocolForm(ctx, { project, onSubmit })`。用户可以在表单里改任何值。
- `onSubmit({ protocol })`：`POST /protocols`（`action` 用"保存协议"），然后 `POST /guide/sessions/{id}/saved {protocol_id, version}`，再调用 `onSaved`，进入第 8 步。

- [ ] **Step 1: 写失败的测试**

```js
test("the form draft rebuilds exactly the reviewed protocol", async () => {
  // fixture 的 protocol 按 buildProtocol 的输出形状写。把 protocolFormDraft(protocol, { saveAs: "" }) 交给 protocolForm，
  // 在 fake DOM 里提交，从 api.calls 取出发送的 protocol：assert.deepEqual(sent, protocol)
});
test("saving posts the protocol, then tells the guide", async () => {
  // 提交表单 → api.calls 依次是 POST /protocols、POST /guide/sessions/guide-1/saved {protocol_id, version}
});
test("problems are listed before the form", async () => { /* fixture 的 problems 显示在"保存前要解决的问题"下面 */ });
test("a missing step links back to it", async () => { /* missing: ["scale"] → 出现指向规模那一步的按钮 */ });
```

- [ ] **Step 2: 跑测试，确认失败** → FAIL
- [ ] **Step 3: 实现 `guide-draft.js` 和 `guide-review.js`**
- [ ] **Step 4: 跑测试，确认通过**（`node --test tests/web/*.test.mjs`，加上对新文件跑 `node --check`）→ PASS
- [ ] **Step 5: 提交** `git commit -m "feat: the guide reviews its protocol in the normal form and records the save"`

---

### Task 8: 入口、轮次与目标（第 8 步）、文档

**Files:**
- Modify: `pages/projects.js`（新增"按引导新建"表单）；`pages/project.js`（协议区加"按引导建立或修改协议"按钮）；`pages/guide-review.js`（第 8 步）；`i18n/guide.{en,zh}.js`
- Create: `docs/wiki/zh-CN/Guided-Setup.md`, `docs/wiki/en/Guided-Setup.md`
- Modify: `docs/wiki/{zh-CN,en}/_Sidebar.md`；`docs/wiki/{zh-CN,en}/Run-a-Research-Round.md`（第 1 步加一段，链接引导）
- Test: `tests/web/guide-entry.test.mjs`

**Interfaces:**
- Consumes: 现有路由 `POST /projects`、`POST /projects/{id}/budget`（要重新验证身份，传 `action`）、`POST /rounds`、`POST /goals`；Task 5 的 `POST /guide/sessions`。
- Produces：`pages/guide-review.js` 里 `export function roundStep(ctx, { session, saved })`

行为：
- **项目列表页的"按引导新建"**（第 0 步）：字段是项目名、`max_calls`（预填 `100`）、`max_cost`（预填 `10`）。依次发 `POST /projects`、`POST /projects/{id}/budget`、`POST /guide/sessions {project_id, lang: ctx.lang}`，然后跳到 `hrefFor("guide", { sessionId })`。预算路由回 404（这个部署没有模型和预算）时，跳过预算并提示。默认值 100 次 / 10 美元是本计划的决定，页面上可以改。
- **项目页的按钮**：`POST /guide/sessions {project_id, lang}`，然后跳过去。
- **第 8 步**：按钮"建轮次"发 `POST /rounds {project_id, protocol_id}`；然后是目标文本框（预填协议的研究问题），提交发 `POST /goals {project_id, round_id, goal, language: ctx.lang}`；成功后给出轮次页的链接。这一步可以跳过。
- **wiki《用引导建立研究》**（中英）：分步说明，每步写清楚"系统给什么选项、你要决定什么"，并说明来源标记、沿用旧版本、保存仍由你点。《运行一轮研究》第 1 步加一段，指向这一页。

- [ ] **Step 1: 写失败的测试**

```js
test("the guided new-project form creates project, budget and session, then opens the guide", async () => {
  // answers: POST /projects → {project_id: "project-9"}；budget → {}；/guide/sessions → {session_id: "guide-9"}
  // 断言 api.calls 顺序，budget 请求体是 {max_calls: 100, max_cost: 10}，navigate 到 "#/guide/guide-9"
});
test("the project page opens a guide for that project", async () => { ... });
test("the round step creates the round, then sends the goal in the page language", async () => {
  // POST /rounds {project_id, protocol_id}；POST /goals 请求体含 round_id、goal、language: "zh"
});
```

- [ ] **Step 2: 跑测试，确认失败** → FAIL
- [ ] **Step 3: 实现入口、第 8 步和 wiki 页面**
- [ ] **Step 4: 跑全部检查**

Run: `ruff check src tests && ruff format --check src tests && pytest -q && node --test tests/web/*.test.mjs`
Expected: 全部 PASS（包括 `tests/docs/` 里对 wiki 的检查）

- [ ] **Step 5: 提交** `git commit -m "feat: start the guide from the project list or a project, and finish with a round and goal"`

---

## 这一块完成时

- 不开模型也能从项目列表一路走到"轮次已建、目标已提"。
- 第 2 块（接模型）在这些步骤卡上加"推荐和理由"、学名候选和 NCBI 查询，路由和事件格式不变（`suggested` 事件已经预留）。
