# 证据卡有效性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新证据卡能写明变量、作物和适用条件；卡片之间能记录取代、矛盾、撤回；卡片状态在读取时推算，可以回溯到任一时间点；引用失效卡的运行单在提交、审批、换单时被挡住；操作员能把已交付轮次的结论转成本项目的卡。

**Architecture:**
- 存储：在 archive 数据库上新开一个命名空间 `evidence_ledger`（做法和 `runtime_mirror` 相同），建四张只追加的表。
- `archive/evidence_status.py`：纯函数，从记录推算状态。
- `archive/evidence_book.py`：按项目取卡和状态。
- `archive/evidence_relations.py`：写入规则。
- 检查集中在 `planning/evidence_validity.py`：挡住的一组接到 `runtime.py` 的 `validate` lambda 上；提示的一组接到计划角色的 `validate` 工具和 `review_json`。
- 工作台、模型工具、日报和控制台都只调用上面这些函数。

**Tech Stack:** Python 3.11+ / FastAPI / pydantic v2（`Model` = frozen, extra="forbid"）/ SQLite（`Database.migrate(namespace, steps)` 只能追加步骤）；控制台为原生 ES 模块，Node 20 `node --test`。

**Spec:** `docs/superpowers/specs/2026-11-19-evidence-validity-design.md`（下称"设计"；§ 编号指它）

## Global Constraints

- **只追加**：卡片正文写入后不改。关系、审核、撤销、轮次卡来源各是一张只追加的表。第一条审核、第一条撤销生效，后来的不覆盖（`INSERT OR IGNORE`，同 `verify_evidence`）。
- **迁移**：只追加步骤。新表放在新命名空间 `"evidence_ledger"`，不动 `archive/store.py` 的 `STEPS`。
- **时间**：一律存 REAL（epoch 秒），与现有 archive 表一致。设计 §5.2 写成了 TEXT，以本计划为准。
- **规模**：
  - 文件 ≤ 800 行、函数 ≤ 30 行、嵌套 ≤ 3 层。
  - `runtime.py` 现有 786 行，`tests/test_runtime_size.py` 要求 ≤ 800，本计划在里面最多加 6 行。
  - `workflow/service.py`（863 行）不加代码。
- **先写测试**。每个任务结束时，`pytest -q`、`ruff check src tests scripts`、`ruff format --check src tests scripts` 都要通过；改了控制台的任务另跑 `node --test tests/web/*.test.mjs`。
- **模型的权限**：模型写下的记录永远不是已核实的；模型不能审核或撤销关系，也不能提议 `local` 卡。
- **上限**（设计 §5.1、§5.5、§5.6）：

  | 项目 | 上限 |
  |---|---|
  | `claim` | 1000 字 |
  | `citation` | 500 字 |
  | `unit` | 40 字 |
  | `cultivar` | 200 字 |
  | `growth_stage` | 100 字 |
  | `conditions_note` | 500 字 |
  | `conditions` | 8 条 |
  | 关系理由 | 500 字 |
  | 每个任务提议的关系 | 10 条 |
  | 日报里的失效卡 | 5 行 |

- **状态优先顺序**：`retracted` > `dependency_invalid` > `superseded` > `active`（设计 §5.3）。
- **多用户关闭**（`access is None`）：不做操作员权限检查，但卡片的可见范围和状态仍按项目区分（设计 §6）。
- **代码登记**：新的 finding 代码登记在 `codes.py` 的 `"finding"` 下；新的拒绝理由用 `denial_codes.py` 的 `_register` 登记。控制台的中英文文案要同步改（`web/workbench/i18n/codes.{en,zh}.js`、`messages.{en,zh}.js`）。`tests/workbench/test_console_known_codes.py`、`test_message_codes.py` 和 `tests/web/messages.test.mjs` 会检查这三处是否一致。
- **提交信息**：格式为 `<type>: <描述>`，末行是 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。

## Review Focus

1. **旧卡**：本计划之前存的卡没有新字段，`unit` 也可能不是目录单位（如 `"umol m-2 s-1"`）。这些卡的列表、查询、提交、审批都要照旧工作；没填 `variable` 的卡不做单位检查。→ Task 1、Task 6 的测试。
2. **传感器名不在目录里**：反馈规则的 `sensor` 有时是设备自己的名字（如 `"tempB"`），`catalog.resolve` 会返回 None。这时不比对变量、不报错，也不给 `variable_mismatch`。→ Task 6。
3. **`as_of` 恰好等于确认时刻或撤销时刻**：确认时刻 ≤ `as_of` 算已生效，撤销时刻 ≤ `as_of` 算已结束。→ Task 3。
4. **报告没有结论**：报告 JSON 的 `conclusion` 缺失、为空或不是字符串时，转卡被拒（`round_card_no_conclusion`），不能生成空卡。→ Task 11。
5. **提议之后状态变了**：模型提议"A 取代 B"，确认之前 B 已被别人取代。此时确认被拒（`relation_already_superseded`），这条提议仍可驳回。→ Task 5。

---

### Task 1: 目录 `current` 与卡片的新字段

**Files:**
- Modify: `src/growbridge/vocab/catalog.py`（`Catalog` 类内，`same` 之后）
- Modify: `src/growbridge/archive/models.py:626-635`（`EvidenceCard`；`ApplicabilityRange` 放在它前面）
- Create: `src/growbridge/vocab/card_checks.py`
- Test: `tests/vocab/test_vocab_catalog.py`（追加）、`tests/vocab/test_card_checks.py`、`tests/archive/test_archive_evidence_fields.py`

**Interfaces:**
- Produces:
  - `Catalog.current(name: str) -> Variable | None`：先 `resolve(name)`，再沿 `replaced_by` 走到底；走回已经过的编号时返回 None。
  - `ApplicabilityRange(Model)`：`variable: str`、`min: float | None = None`、`max: float | None = None`（两者 `allow_inf_nan=False`）。
  - `EvidenceCard` 新字段：
    - `variable: str | None = None`
    - `conditions: tuple[ApplicabilityRange, ...] = ()`
    - `crop_taxon: str = ""`、`cultivar: str = ""`、`growth_stage: str = ""`、`conditions_note: str = ""`
    - 加 `@model_serializer(mode="wrap")`，序列化时去掉这六个字段中为 None 或为空的，做法照 `ResearchProtocol._without_empty_fields`。
  - `vocab/card_checks.py`：
    - 常量：`MAX_CONDITIONS = 8`、`GROWTH_STAGE_MAX = 100`、`CONDITIONS_NOTE_MAX = 500`。
    - `card_problems(card: EvidenceCard, catalog: Catalog) -> list[str]`。
    - `with_catalog_unit(card: EvidenceCard, catalog: Catalog) -> EvidenceCard`：`variable` 和 `unit` 都不为空时，返回 `unit` 换成 `catalog.unit_aliases.get(unit, unit)` 的副本。

- [ ] **Step 1: Write the failing tests**

```python
# tests/vocab/test_vocab_catalog.py（追加）
def test_current_follows_replaced_by_to_the_end():
    assert WITH_OLD.current("canopy_growth_old").id == "canopy_area_growth"
    assert WITH_OLD.current("temp").id == "air_temperature"   # an alias resolves first
    assert WITH_OLD.current("nope") is None

def test_current_returns_none_on_a_replacement_loop():
    looped = load_catalog(packaged_text() + LOOP_ENTRIES)  # a -> b -> a, both deprecated
    assert looped.current("loop_a") is None
```

```python
# tests/vocab/test_card_checks.py —— 用 packaged_catalog() 与 tests/vocab_support.py 的 WITH_OLD
def card(**fields) -> EvidenceCard:
    return EvidenceCard(id="ev-1", source_class="paper", citation="Doe 2024", claim="c", **fields)

def test_a_card_without_the_new_fields_has_no_problems():
    assert card_problems(card(value=200.0, unit="umol m-2 s-1"), CATALOG) == []

def test_an_alias_is_refused_with_the_standard_id():
    assert card_problems(card(variable="temp"), CATALOG) == [
        "variable temp is an alias: use the standard ID air_temperature"]

def test_a_deprecated_variable_is_refused_with_its_replacement():
    assert card_problems(card(variable="canopy_growth_old"), WITH_OLD) == [
        "variable canopy_growth_old is deprecated: use canopy_area_growth"]

def test_a_factor_variable_is_refused():
    assert card_problems(card(variable="light"), CATALOG) == [
        "variable light is a factor: its levels are not comparable across sources"]

def test_a_value_with_a_variable_needs_the_catalog_unit():
    assert card_problems(card(variable="air_temperature", value=24.0, unit="C"), CATALOG) == []
    assert card_problems(card(variable="air_temperature", value=24.0, unit="K"), CATALOG) == [
        "unit K is not the catalog unit Cel of air_temperature"]
    assert card_problems(card(variable="air_temperature", value=24.0), CATALOG) == [
        "a value of air_temperature needs its unit Cel"]
    fixed = with_catalog_unit(card(variable="air_temperature", value=24.0, unit="C"), CATALOG)
    assert fixed.unit == "Cel"

def test_conditions_follow_the_catalog():
    rng = ApplicabilityRange
    assert card_problems(card(conditions=(rng(variable="air_relative_humidity", min=80, max=70),)),
                         CATALOG) == ["condition air_relative_humidity: min 80 is above max 70"]
    assert card_problems(card(conditions=(rng(variable="air_relative_humidity", max=120),)),
                         CATALOG) == ["condition air_relative_humidity: 120 is outside 0–100"]
    assert card_problems(card(conditions=(rng(variable="air_temperature"),)), CATALOG) == [
        "condition air_temperature: give min, max or both"]
    two = (rng(variable="air_temperature", min=18), rng(variable="temp", max=26))
    assert "condition temp: variable temp is an alias: use the standard ID air_temperature" in \
        card_problems(card(conditions=two), CATALOG)
    nine = tuple(rng(variable="air_temperature", min=i) for i in range(9))
    assert "at most 8 conditions" in card_problems(card(conditions=nine), CATALOG)

def test_crop_and_free_text_limits():
    assert card_problems(card(crop_taxon="NCBITaxon:4236", cultivar="Grand Rapids"), CATALOG) == []
    assert card_problems(card(crop_taxon="lettuce"), CATALOG) == [
        "crop_taxon lettuce is not NCBITaxon:<number>"]
    assert card_problems(card(growth_stage="x" * 101), CATALOG) == [
        "growth_stage is longer than 100 characters"]
```

```python
# tests/archive/test_archive_evidence_fields.py
def test_an_old_card_dumps_exactly_as_before():
    old = EvidenceCard(id="ev-1", source_class="handbook", citation="H", claim="c", value=1.0, unit="x")
    assert set(old.model_dump(mode="json")) == {
        "id", "source_class", "citation", "claim", "value", "unit", "verified", "calibrated"}

def test_new_fields_round_trip_through_the_archive(archive):
    new = EvidenceCard(id="ev-2", source_class="paper", citation="P", claim="c",
                       variable="air_temperature", value=24.0, unit="Cel",
                       conditions=(ApplicabilityRange(variable="co2_concentration", max=800),),
                       crop_taxon="NCBITaxon:4236", growth_stage="head")
    archive.add_evidence(new, source="operator:op", verified_by="op")
    (stored,) = archive.evidence(["ev-2"])
    assert stored.conditions[0].max == 800 and stored.crop_taxon == "NCBITaxon:4236"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/vocab/test_card_checks.py tests/vocab/test_vocab_catalog.py tests/archive/test_archive_evidence_fields.py -v`
Expected: FAIL（`current`、`ApplicabilityRange`、`card_problems` 未定义）

- [ ] **Step 3: Implement**
  - 卡片的变量和每条条件的变量，都复用 `vocab/checks.py` 的 `_variable_problems(name, catalog, frozenset())` 检查。`declared_before` 传空集合，弃用编号就一律被拒。另外加上 `factor` 类的拒绝。
  - 条件里的问题，前缀写 `"condition {variable}: "`。
  - `crop_taxon` 或 `cultivar` 不为空时，才调用 `taxon_problems(crop_taxon, cultivar)`。
  - 目录的 `min` 或 `max` 为 None 时，不检查那一侧。
  - 测试用的 `LOOP_ENTRIES` 加在 `tests/vocab_support.py`：两个互相指向的 deprecated 变量。

- [ ] **Step 4: Run them to verify they pass**

Run: 同 Step 2。Expected: PASS；再跑 `pytest -q`，全部通过（旧卡的测试不受影响）。

- [ ] **Step 5: Commit**

```bash
git add src/growbridge/vocab src/growbridge/archive/models.py tests/vocab tests/vocab_support.py tests/archive/test_archive_evidence_fields.py
git commit -m "feat: evidence cards name a catalog variable, crop and applicability ranges"
```

---

### Task 2: 关系与来源的存储（`EvidenceLedger`）

**Files:**
- Create: `src/growbridge/archive/evidence_ledger.py`
- Modify: `src/growbridge/archive/store.py`（`Archive.__init__` 加 `self.ledger`；加 `invalidated_at`）
- Test: `tests/archive/test_evidence_ledger.py`

**Interfaces:**
- Consumes: `Database`、`Clock`、`archive.ids.new_id`、`Label`（`archive/models.py:32`）。
- Produces（都在 `archive/evidence_ledger.py`）：
  - `NAMESPACE = "evidence_ledger"`。`STEPS` 建以下四张表：
    - `evidence_relations(id TEXT PRIMARY KEY, seq INTEGER NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('supersedes','contradicts','retracts')), subject_id TEXT NOT NULL, object_id TEXT, reason TEXT NOT NULL, source TEXT NOT NULL, task_id TEXT, project_id TEXT, proposed_in TEXT, at REAL NOT NULL)`，另在 `subject_id`、`object_id` 上各建一个索引；
    - `evidence_relation_reviews(relation_id TEXT PRIMARY KEY, decision TEXT NOT NULL CHECK (decision IN ('confirmed','rejected')), reviewer TEXT NOT NULL, note TEXT NOT NULL, at REAL NOT NULL)`；
    - `evidence_relation_withdrawals(relation_id TEXT PRIMARY KEY, actor TEXT NOT NULL, reason TEXT NOT NULL, at REAL NOT NULL)`；
    - `evidence_origins(card_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, round_id TEXT NOT NULL, report_artifact_id TEXT NOT NULL UNIQUE, snapshot_ids TEXT NOT NULL, label TEXT NOT NULL, at REAL NOT NULL)`，其中 `snapshot_ids` 存 JSON 数组。
  - 模型类型：
    - `RelationKind = Literal["supersedes", "contradicts", "retracts"]`
    - `EvidenceRelation(Model)`：`id, kind: RelationKind, subject_id, object_id: str | None, reason, source, task_id: str | None, project_id: str | None, proposed_in: str | None, at: float`
    - `RelationReview(Model)`：`relation_id, decision: Literal["confirmed","rejected"], reviewer, note: str = "", at: float`
    - `RelationWithdrawal(Model)`：`relation_id, actor, reason, at: float`
    - `RelationRecord(Model)`：`relation, review: RelationReview | None, withdrawal: RelationWithdrawal | None`；属性 `state -> Literal["pending","confirmed","rejected","withdrawn"]`。
    - `EvidenceOrigin(Model)`：`card_id, project_id, round_id, report_artifact_id, snapshot_ids: tuple[str, ...], label: Label, at: float`
  - `class EvidenceLedger(db: Database, clock: Clock)` 的方法：
    - `add_relation(relation: EvidenceRelation, confirmed_by: str | None = None, note: str = "") -> RelationRecord`：在同一事务里写入关系；`confirmed_by` 不为空时，同时写一条 confirmed 审核，`at` 与关系相同。
    - `review(relation_id: str, decision: str, reviewer: str, note: str = "") -> RelationRecord`
    - `withdraw(relation_id: str, actor: str, reason: str) -> RelationRecord`
    - `record(relation_id: str) -> RelationRecord | None`
    - `records(project_id: str | None) -> tuple[RelationRecord, ...]`：返回 `project_id IS NULL` 的行，以及等于给定项目的行，按 `seq` 排序。传 None 时只返回 `project_id IS NULL` 的行。
    - `proposed_by(task_id: str) -> int`
    - `add_origin(origin: EvidenceOrigin) -> None`、`origin(card_id: str) -> EvidenceOrigin | None`、`origins() -> dict[str, EvidenceOrigin]`、`origin_of_report(artifact_id: str) -> EvidenceOrigin | None`
  - `Archive` 上的两处：
    - `Archive.ledger: EvidenceLedger`
    - `Archive.invalidated_at(record_ids: Iterable[str]) -> float | None`：在 `invalidations` 表里，取 `dependent_id` 属于这些编号的行中最早的 `at`。

- [ ] **Step 1: Write the failing tests**

```python
def relation(**over) -> EvidenceRelation:
    base = dict(id="rel-1", kind="supersedes", subject_id="ev-new", object_id="ev-old",
                reason="2nd edition", source="operator:op", task_id=None, project_id=None,
                proposed_in=None, at=0.0)
    return EvidenceRelation(**{**base, **over})

def test_an_operator_relation_is_confirmed_in_the_same_step(archive, clock):
    rec = archive.ledger.add_relation(relation(at=clock.now()), confirmed_by="op")
    assert rec.state == "confirmed" and rec.review.at == rec.relation.at

def test_the_first_review_and_the_first_withdrawal_stay(archive):
    archive.ledger.add_relation(relation(source="model:planner"))
    archive.ledger.review("rel-1", "confirmed", "op", "ok")
    assert archive.ledger.review("rel-1", "rejected", "op2").review.decision == "confirmed"
    archive.ledger.withdraw("rel-1", "op", "conditions differ")
    assert archive.ledger.withdraw("rel-1", "op2", "again").withdrawal.actor == "op"
    assert archive.ledger.record("rel-1").state == "withdrawn"

def test_records_of_a_project_include_the_global_ones_only(archive):
    archive.ledger.add_relation(relation(id="g"))
    archive.ledger.add_relation(relation(id="p", project_id="P"))
    archive.ledger.add_relation(relation(id="q", project_id="Q"))
    assert [r.relation.id for r in archive.ledger.records("P")] == ["g", "p"]
    assert [r.relation.id for r in archive.ledger.records(None)] == ["g"]

def test_reviewing_an_unknown_relation_is_refused(archive):
    with pytest.raises(ValueError):
        archive.ledger.review("nope", "confirmed", "op")

def test_one_origin_per_report_and_its_snapshots_round_trip(archive):
    origin = EvidenceOrigin(card_id="ev-r", project_id="P", round_id="r1",
                            report_artifact_id="art-1", snapshot_ids=("snap-1", "snap-2"),
                            label="confirmatory", at=0.0)
    archive.ledger.add_origin(origin)
    assert archive.ledger.origin_of_report("art-1") == origin
    with pytest.raises(sqlite3.IntegrityError):
        archive.ledger.add_origin(origin.model_copy(update={"card_id": "ev-r2"}))

def test_invalidated_at_is_the_earliest_invalidation(archive, clock):
    ...  # 用 mark_dependents_invalid 依次标记两个快照，时间 t1 < t2；断言结果 == t1；没被标记的编号返回 None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `pytest tests/archive/test_evidence_ledger.py -v` → FAIL（模块不存在）

- [ ] **Step 3: Implement** `archive/evidence_ledger.py`，以及 `Archive` 的两处改动。`seq` 取 `COALESCE(MAX(seq), 0) + 1`，与 `Archive._next_seq` 的做法相同。

- [ ] **Step 4: Run them to verify they pass** — 同 Step 2 → PASS；`pytest tests/archive -q` 全部通过。

- [ ] **Step 5: Commit**

```bash
git add src/growbridge/archive/evidence_ledger.py src/growbridge/archive/store.py tests/archive/test_evidence_ledger.py
git commit -m "feat: append-only ledger of evidence relations and round-card origins"
```

---

### Task 3: 状态推算（纯函数）

**Files:**
- Create: `src/growbridge/archive/evidence_status.py`
- Test: `tests/archive/test_evidence_status.py`

**Interfaces:**
- Consumes: `RelationRecord`（Task 2）。
- Produces:
  - `Validity = Literal["active", "superseded", "retracted", "dependency_invalid"]`
  - `Replacement(Model)`：`card_id: str`、`validity: Validity`
  - `CardStatus(Model)`：
    - 字段：`card_id`、`validity: Validity = "active"`、`superseded_by: str | None = None`、`current_replacement: Replacement | None = None`、`retracted_reason: str | None = None`、`contested_with: tuple[str, ...] = ()`、`pending: tuple[str, ...] = ()`；
    - 属性 `blocks -> bool`，即 `validity != "active"`。
  - `derive_statuses(card_ids: Iterable[str], records: Sequence[RelationRecord], invalid_at: Mapping[str, float], as_of: float, viewer_project: str | None) -> dict[str, CardStatus]`

推算规则（设计 §5.3），测试逐条覆盖：
- **生效**：审核为 confirmed、`review.at <= as_of`，并且没有撤销，或 `withdrawal.at > as_of`。
- **待确认**：`relation.at <= as_of`，到 `as_of` 时还没有审核。只有 `proposed_in` 为 None 或等于 `viewer_project` 时才计入。
- **依赖失效**：`invalid_at[card] <= as_of`。
- **`current_replacement`**：沿 `superseded_by` 一直走到底；遇到已经走过的卡就停在那里。
- **`contested_with`**：生效中的 `contradicts`，且对方在 `as_of` 时为 `active`。

- [ ] **Step 1: Write the failing tests**

```python
def test_a_pending_relation_changes_nothing_but_shows_as_pending(): ...
    # 待确认的 supersedes A->B：B.validity == "active"，B.pending == ("rel-1",)
def test_a_confirmed_supersede_names_the_end_of_the_chain():
    # C supersedes B，B supersedes A：A.superseded_by == "B"，A.current_replacement == Replacement(card_id="C", validity="active")
def test_a_retracted_end_of_chain_keeps_the_old_card_superseded():
    # B supersedes A，然后 B 被撤回：A.validity == "superseded"，A.current_replacement.validity == "retracted"
def test_precedence_retracted_then_invalid_then_superseded():
    # 同一张卡同时被撤回、依赖失效、被取代 -> "retracted"；去掉撤回 -> "dependency_invalid"
def test_as_of_bounds_are_inclusive_at_confirmation_and_at_withdrawal():
    # 100 时确认，200 时撤销：as_of=99 为 active，100 为 superseded，199 为 superseded，200 为 active
def test_invalidation_counts_from_its_time():
    # invalid_at={"R": 50}：as_of=49 为 active，as_of=50 为 dependency_invalid
def test_a_contradiction_counts_only_while_the_other_card_is_active():
    # A contradicts B（已确认）；B 后来被 C 取代：取代之前 A.contested_with == ("B",)，之后 == ()
def test_a_pending_proposal_of_another_project_is_not_shown():
    # proposed_in="P"：viewer_project="Q" 时 pending == ()；viewer_project="P" 时 == ("rel-1",)
```

- [ ] **Step 2: Run** `pytest tests/archive/test_evidence_status.py -v` → FAIL
- [ ] **Step 3: Implement** `derive_statuses`。先为每张出现过的卡算出它自身的状态，再算替代链和矛盾；每个函数 ≤ 30 行。
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit** — `git commit -m "feat: derive evidence card status from relation records at any time"`

---

### Task 4: 按项目取卡与状态（`evidence_book`）

**Files:**
- Create: `src/growbridge/archive/evidence_book.py`
- Test: `tests/archive/test_evidence_book.py`

**Interfaces:**
- Consumes: `Archive.evidence`、`Archive.ledger`、`Archive.invalidated_at`、`derive_statuses`。
- Produces:
  - `card_project(archive: Archive, card_id: str) -> str | None`：轮次卡返回其来源记录里的项目，其余（公共卡）返回 None。
  - `visible_cards(archive: Archive, project_id: str | None) -> dict[str, EvidenceCard]`：公共卡，加上 `project_id` 那个项目的项目卡。
  - `card_statuses(archive: Archive, card_ids: Iterable[str], project_id: str | None, as_of: float | None = None) -> dict[str, CardStatus]`：
    - 只返回在该项目可见的卡；
    - `as_of` 默认取 `archive.clock.now()`；
    - 轮次卡的 `invalid_at` 取 `invalidated_at([report_artifact_id, *snapshot_ids])`；
    - `records` 取 `archive.ledger.records(project_id)`。

- [ ] **Step 1: Write the failing tests**

```python
def test_another_projects_round_card_is_invisible(archive): ...
    # 来源记录 project_id="P" 的卡：visible_cards(archive, "Q") 里没有它；card_statuses(archive, [id], "Q") == {}
def test_a_project_relation_does_not_change_the_status_elsewhere(archive): ...
    # P 的轮次卡 R 与公共卡 H 有已确认的矛盾（project_id="P"）：在 "P" 里 H.contested_with == ("R",)；在 "Q" 和 None 里 == ()
def test_a_round_card_is_invalid_once_its_snapshot_is_marked(archive): ...
    # 标记 snapshot_ids 里的一个快照 -> validity == "dependency_invalid"
```

- [ ] **Step 2–4:** `pytest tests/archive/test_evidence_book.py -v`：先 FAIL，实现后 PASS。
- [ ] **Step 5: Commit** — `git commit -m "feat: evidence cards and status as seen from one project"`

---

### Task 5: 关系的写入规则

**Files:**
- Create: `src/growbridge/archive/evidence_relations.py`
- Modify: `src/growbridge/denial_codes.py`（登记下面的拒绝理由）
- Test: `tests/archive/test_evidence_relations.py`

**Interfaces:**
- Consumes: Task 2–4。
- Produces:
  - 常量：`REASON_MAX = 500`、`MAX_RELATION_PROPOSALS_PER_TASK = 10`、`MODEL_RELATION_SOURCE = "model:planner"`。
  - `RelationRequest(Model)`：`kind: RelationKind`、`card_id: str`、`other_card_id: str | None = None`、`reason`（去掉首尾空白后 1–500 字）。
  - `class RelationRefused(ValueError)`：带 `reason: str`、`message: str`、`params: dict`。
  - `relation_scope(archive, request) -> str | None`：返回两张卡里项目卡所属的项目；两张卡分属不同项目时，抛 `relation_cross_scope`。
  - `propose_relation(archive: Archive, request: RelationRequest, task_id: str, project_id: str) -> RelationRecord`：存为待确认，`source = MODEL_RELATION_SOURCE`，`proposed_in = project_id`；配额满时抛 `quota_proposal_limit`。
  - `record_relation(archive: Archive, request: RelationRequest, actor_id: str, viewer_project: str | None) -> RelationRecord`：同一步确认，`source = f"operator:{actor_id}"`。
  - `review_relation(archive: Archive, relation_id: str, decision: Literal["confirmed","rejected"], reviewer: str, note: str, viewer_project: str | None) -> RelationRecord`
  - `withdraw_relation(archive: Archive, relation_id: str, actor: str, reason: str, viewer_project: str | None) -> RelationRecord`

拒绝理由。括号里是 params；`relation_shape` 和 `relation_self` 用 `_register("param", ...)` 登记，其余用 `_register("state", ...)`：
- `relation_unknown_card (card_id)`：卡不存在，或属于 `viewer_project` 以外的项目；
- `relation_shape (kind)`：`supersedes` 或 `contradicts` 没有给另一张卡，或者 `retracts` 给了另一张卡；
- `relation_self ()`；
- `relation_cross_scope (kind)`：`supersedes` 的两张卡不在同一范围（设计 §5.0 第 6 条），或者任何关系的两张卡分属两个项目；
- `relation_card_inactive (card_id, validity)`：取代者不是 `active`，或者要撤回的卡已经撤回；
- `relation_already_superseded (card_id, replacement_id)`；
- `relation_duplicate (relation_id)`：同类型、同一对卡已有待确认，或已确认且未撤销的关系；`contradicts` 不区分两张卡的先后；
- `relation_not_pending (relation_id, state)`、`relation_not_confirmed (relation_id, state)`；
- `relation_note_required ()`：确认两张公共卡之间的模型提议时没写 `note`。

另外两种情况沿用现有理由：未知的关系编号用 `record_not_found`（`record_kind="evidence_relation"`）；配额用 `quota_proposal_limit (max_proposals)`。

两条实现要求：
- `contradicts` 存储时，`subject_id` 取两张卡中编号较小的那张（设计 §5.2）。
- 确认前要把写入规则重新检查一遍，查重时排除这条关系本身。

- [ ] **Step 1: Write the failing tests** — 每条拒绝理由各写一个测试，断言 `exc.reason`。另外加：

```python
def test_a_supersede_chain_cannot_loop(archive): ...
    # 记 B supersedes A（已确认）；再记 A supersedes B -> relation_card_inactive（A 已被取代）
def test_confirming_after_the_object_was_superseded_elsewhere_is_refused(archive): ...
    # 模型提议 A supersedes H（待确认）；操作员另记 B supersedes H；确认那条提议 -> relation_already_superseded；之后驳回成功
def test_a_contradiction_is_stored_once_whatever_the_order(archive): ...
    # 记 contradicts(b, a)；再记 contradicts(a, b) -> relation_duplicate；存下的 subject_id == "a"
def test_a_round_card_cannot_supersede_a_public_card(archive): ...
    # -> relation_cross_scope；同一对卡改记 contradicts 则成功，project_id == 该项目
def test_the_eleventh_proposal_of_a_task_is_refused(archive): ...
```

- [ ] **Step 2–4:** `pytest tests/archive/test_evidence_relations.py tests/workbench/test_message_codes.py -v`：先 FAIL，实现后 PASS。
- [ ] **Step 5: Commit** — `git commit -m "feat: rules for recording, reviewing and withdrawing evidence relations"`

---

### Task 6: 检查（挡住与提示）

**Files:**
- Create: `src/growbridge/planning/evidence_validity.py`
- Modify: `src/growbridge/codes.py`（在 `"finding"` 下登记 10 个新代码）
- Test: `tests/planning/test_evidence_validity.py`

**Interfaces:**
- Consumes: `CardStatus`、`EvidenceOrigin`、`visible_cards`、`card_statuses`、`Catalog.current`；`planning/validate.py` 的 `_evidence_refs` 与 `USER_INPUT_PREFIX`；`planning/findings.py` 的 `block`、`hint`、`source_text`。
- Produces:
  - `cited_card_ids(sheet: RunSheet) -> tuple[str, ...]`：去掉 `user:` 引用和空引用，去重并保持顺序。
  - `check_evidence_validity(sheet: RunSheet, statuses: Mapping[str, CardStatus]) -> tuple[Finding, ...]`：每个引用点一条，`blocking=True`。
  - `check_evidence_fit(sheet: RunSheet, cards: Mapping[str, EvidenceCard], statuses: Mapping[str, CardStatus], origins: Mapping[str, EvidenceOrigin], catalog: Catalog, crop_taxon: str) -> tuple[Finding, ...]`：只给提示。
  - `evidence_gate(sheet: RunSheet, archive: Archive) -> tuple[Finding, ...]`，等于 `check_evidence_validity(sheet, card_statuses(archive, cited_card_ids(sheet), sheet.project_id))`。
  - `evidence_hints(sheet: RunSheet, archive: Archive, catalog: Catalog, crop_taxon: str) -> tuple[Finding, ...]`
  - `stale_evidence_lines(sheet: RunSheet, archive: Archive, limit: int = 5) -> tuple[str, ...]`：每行格式为 `"{source_text}: card {card_id} is {validity}; use {replacement_id}"`；没有替代卡时去掉 `; use …`。

代码与 params（登记进 `codes.py`）：

| 代码 | blocking | params |
|---|---|---|
| `superseded_source` | 是 | `source_kind, source, card_id, replacement_id, replacement_validity` |
| `retracted_source` | 是 | `source_kind, source, card_id, reason` |
| `dependency_invalid_source` | 是 | `source_kind, source, card_id` |
| `contested_source` | 否 | `source_kind, source, card_id, others`（逗号连接的编号） |
| `pending_relation` | 否 | `source_kind, source, card_id, relations` |
| `variable_mismatch` | 否 | `source_kind, source, card_id, rule_variable, card_variable` |
| `evidence_unit_mismatch` | 否 | `source_kind, source, card_id, rule_unit, card_unit` |
| `crop_mismatch` | 否 | `source_kind, source, card_id, card_taxon, protocol_taxon` |
| `uncataloged_card` | 否 | `source_kind, source, card_id` |
| `exploratory_finding` | 否 | `source_kind, source, card_id, label` |

各代码什么时候给：
- **`superseded_source`**：没有替代卡时，`replacement_id` 和 `replacement_validity` 为 None。
- **`variable_mismatch`、`evidence_unit_mismatch`、`uncataloged_card`**：只检查反馈规则。
  - `catalog.current(rule.sensor)` 或 `catalog.current(card.variable)` 为 None 时，不给 `variable_mismatch`（见 Review Focus 第 2 条）。
  - `card.variable` 为空时也不给 `variable_mismatch`；这时卡片有数值，就给 `uncataloged_card`。
- **`crop_mismatch`**：三种引用都检查，只在卡片和协议都写了 `crop_taxon` 时才比较。
- **`exploratory_finding`**：只对有来源记录、且 `label != "confirmatory"` 的卡给。

- [ ] **Step 1: Write the failing tests**（用 `tests/planning/test_planning_evidence.py` 里现成的造运行单助手）

```python
def test_a_superseded_card_blocks_and_names_the_replacement():
    status = CardStatus(card_id="H", validity="superseded", superseded_by="P",
                        current_replacement=Replacement(card_id="P", validity="active"))
    (f,) = check_evidence_validity(sheet_citing("H", rule=True), {"H": status})
    assert (f.code, f.blocking, f.params["replacement_id"]) == ("superseded_source", True, "P")

def test_user_input_and_active_cards_never_block(): ...
def test_a_sensor_alias_matches_the_cards_variable():
    # rule.sensor="temp"、单位 "C"；card.variable="air_temperature"、单位 "Cel" -> 没有任何提示
def test_a_sensor_outside_the_catalog_gives_no_variable_hint():   # Review Focus 2
    # rule.sensor="tempB" -> 没有 variable_mismatch
def test_an_old_card_gets_uncataloged_not_a_unit_hint():          # Review Focus 1
    # card(value=200, unit="umol m-2 s-1")，没有 variable -> 只有 uncataloged_card
def test_crop_mismatch_needs_both_taxa(): ...
def test_a_descriptive_round_card_gets_exploratory_finding(): ...
def test_stale_lines_are_capped_at_five(): ...
```

- [ ] **Step 2–4:** `pytest tests/planning/test_evidence_validity.py tests/planning/test_planning_finding_params.py -v`：先 FAIL，实现后 PASS。
- [ ] **Step 5: Commit** — `git commit -m "feat: evidence validity blocks and evidence fit hints for run sheets"`

---

### Task 7: 接入提交、审批、审阅

**Files:**
- Modify: `src/growbridge/runtime.py:635-643`（`validate` lambda，外加一行 import）
- Modify: `src/growbridge/agents/handlers_planner.py:128-133`（计划角色的 `validate` 工具）
- Modify: `src/growbridge/workbench/rounds.py:160-187`（`review_json`）
- Test: `tests/workflow/test_evidence_gate.py`、`tests/workbench/test_workbench_evidence.py`（追加）

**Interfaces:**
- Consumes: `evidence_gate`、`evidence_hints`、`visible_cards`（Task 4、6）。
- Produces（只改行为，没有新函数）：
  - `runtime.py`：`validate=lambda sheet: (*validate_run_sheet(...原参数...), *evidence_gate(sheet, archive))`。
  - 计划角色的 `validate` 工具：
    - `cards = visible_cards(deps.archive, sheet.project_id)`；
    - 结果依次为 `check_sheet`、`evidence_gate`、`check_evidence(sheet, cards)`、`evidence_hints(...)`；
    - `crop_taxon` 取自 `deps.workflow.store.protocol(sheet.protocol_id, sheet.protocol_version)`，协议不存在时用 `""`。
  - `review_json`：
    - `cards` 改用 `visible_cards(archive, sheet.project_id)`，并追加 `evidence_hints`；
    - 阶段状态不是 `pending_review` 时，三个挡住代码用 `model_copy` 改为 `blocking=False`，这样运行中的阶段页只显示提示（设计 §5.5）。

- [ ] **Step 1: Write the failing tests**

```python
# tests/workflow/test_evidence_gate.py —— WorkflowService 的 validate 用 lambda s: evidence_gate(s, archive)
def test_submitting_a_sheet_that_cites_a_superseded_card_is_refused(): ...
    # submit_run_sheet 返回的 findings 里有 superseded_source，阶段没有建立
def test_approval_is_blocked_once_the_card_is_superseded_before_it(): ...
    # 提交时卡有效；审批前记录取代 -> approve 抛 approval_blocking_findings
def test_a_card_superseded_after_approval_does_not_stop_the_stage(): ...
    # 批准后才记录取代 -> start_stage 成功，阶段在运行
def test_a_new_run_sheet_for_a_running_stage_is_checked(): ...
def test_another_projects_card_counts_as_no_evidence(): ...
    # 运行单引用别的项目的轮次卡 -> 不挡住，check_evidence 给 no_evidence
```

```python
# tests/workbench/test_workbench_evidence.py（追加）
def test_a_running_stage_shows_the_superseded_card_as_a_hint(): ...
    # GET /wb/stages/{id}/run-sheet：superseded_source 的 blocking 为 False，整体 "blocking" 也为 False
```

- [ ] **Step 2: Run** `pytest tests/workflow/test_evidence_gate.py tests/workbench/test_workbench_evidence.py -v` → FAIL
- [ ] **Step 3: Implement**；跑 `wc -l src/growbridge/runtime.py`，确认 ≤ 792 行。
- [ ] **Step 4: Run** 同上，再加 `tests/test_runtime_size.py` → PASS；`pytest -q` 全部通过。
- [ ] **Step 5: Commit** — `git commit -m "feat: superseded, retracted or invalid evidence blocks submission and approval"`

---

### Task 8: 模型工具

**Files:**
- Create: `src/growbridge/agents/evidence_query.py`（把 `EvidenceInput`、`query_cards` 从 `handlers_researcher.py:55-58, 279-298` 搬过来）
- Modify: `src/growbridge/agents/handlers_researcher.py`（改 import）、`src/growbridge/agents/handlers_evidence.py`、`src/growbridge/agents/roles.py:85`（`PLANNER` 的提示）
- Test: `tests/agents/test_evidence_tools.py`

**Interfaces:**
- Consumes: Task 1、4、5。
- Produces:
  - **查询**：
    - `EvidenceInput` 加 `variable: str = ""`。
    - `query_cards(deps: Deps, data: EvidenceInput) -> dict`：项目取 `bound_task(deps).project_id`，返回 `{"cards": [...], "hidden_inactive": n}`。
    - 每张卡在原有字段之外，加 `status`、`superseded_by`、`current_replacement`、`contested_with`、`pending`，以及不为空的新字段和 `label`（只有轮次卡有）。
    - 按文本或变量搜索时，`blocks` 为真的卡不列出，只计入 `hidden_inactive`。
    - 按 `ids` 查询失效的卡时，只返回 `id, source_class, citation, status, superseded_by, current_replacement`。
    - `variable` 过滤比较的是双方经 `catalog.current` 解析后的 id。
  - **提议卡片**：
    - `ProposeCardInput` 加 `variable`、`conditions`、`crop_taxon`、`cultivar`、`growth_stage`、`conditions_note`。
    - `propose_card` 先跑 `card_problems`，有问题时抛 `Denied("param", "; ".join(problems), reason="evidence_card_invalid", params={})`；这个理由在 `denial_codes.py` 用 `_register("param", ("evidence_card_invalid", ()))` 登记。没问题时再调用 `with_catalog_unit`。
  - **新工具 `propose_evidence_relation`**：
    - 输入 `ProposeRelationInput(task_id, kind, card_id, other_card_id=None, reason)`，`writes=True`；
    - 只有 planner 任务能用，沿用 `wrong_task_kind`；
    - 调用 `propose_relation(deps.archive, request, task.id, task.project_id)`，把 `RelationRefused` 转成 `Denied("state", e.message, reason=e.reason, params=e.params)`；
    - 返回 `{"relation_id", "state": "pending", "note": "an operator must confirm it before it changes any card"}`。
  - **`PLANNER` 提示**加三句（设计 §5.6）：
    - 被取代、已撤回、依赖失效的卡不能引用，改引 `current_replacement`；
    - 引用有矛盾的卡时，在起草说明里写明各来源的适用条件和选用理由；
    - 提议关系必须写清理由，不能凭推测。

- [ ] **Step 1: Write the failing tests**

```python
def test_text_search_hides_inactive_cards_and_counts_them(): ...
def test_an_inactive_card_by_id_has_no_claim_or_value(): ...
def test_the_variable_filter_accepts_an_alias(): ...          # variable="temp"
def test_another_projects_card_is_unknown_to_the_query(): ...
def test_a_proposed_card_with_an_alias_is_refused(): ...      # reason == "evidence_card_invalid"
def test_a_proposed_relation_is_pending_and_names_the_project(): ...
    # record.state == "pending"，relation.proposed_in == task.project_id，source == "model:planner"
def test_a_planner_that_read_the_web_has_no_relation_tool(): ...  # 照 writes=True 的现有测试写
```

- [ ] **Step 2–4:** `pytest tests/agents/test_evidence_tools.py tests/agents -q`：先 FAIL，实现后 PASS。
- [ ] **Step 5: Commit** — `git commit -m "feat: evidence tools show status and let the planner propose relations"`

---

### Task 9: 工作台的录卡字段与列表

**Files:**
- Modify: `src/growbridge/workbench/evidence.py`、`src/growbridge/workbench/api.py:288`
- Test: `tests/workbench/test_workbench_evidence.py`（追加）

**Interfaces:**
- Consumes: Task 1、3、4。
- Produces:
  - `add_evidence_routes(router, operator, archive, workflow, access=None)`；`EvidenceRoutes(archive, catalog, access)`。
  - **录卡**：
    - `CardIn` 加 `variable: str | None = None`、`conditions: tuple[ApplicabilityRange, ...] = ()`、`crop_taxon: str = ""`、`cultivar: str = ""`、`growth_stage: str = ""`、`conditions_note: str = ""`。
    - `enter` 先跑 `card_problems`，有问题时抛 `evidence_card_invalid`；没问题时调用 `with_catalog_unit`。
  - **列表** `GET /wb/evidence`：
    - 查询参数：`project_id: str | None`、`as_of: float | None`、`status: Validity | None`、`variable: str | None`。
    - 给了 `project_id` 时，先调用 `project_read(access, actor, project_id, …)`；看不到的项目按"不存在"拒绝。
    - 每条记录在 `entry_json` 之外加 `status`（`CardStatus` 的 JSON）；轮次卡另加 `origin`（`round_id`、`report_artifact_id`、`label`）。

- [ ] **Step 1: Write the failing tests**

```python
def test_an_alias_variable_is_refused_on_entry(bench, client): ...   # 422/400，reason == "evidence_card_invalid"
def test_the_unit_is_stored_as_the_catalog_unit(bench, client): ...  # "C" -> "Cel"
def test_old_style_cards_still_enter_and_list(bench, client): ...    # 原样提交 CARD -> 200
def test_the_list_filters_by_status_and_variable(bench, client): ...
def test_the_list_of_a_project_needs_access_to_it(bench, client): ... # 多用户开启，非项目所有者 -> 被拒
def test_the_list_as_of_shows_the_status_at_that_time(bench, client): ...
```

- [ ] **Step 2–4:** `pytest tests/workbench/test_workbench_evidence.py -v`：先 FAIL，实现后 PASS。
- [ ] **Step 5: Commit** — `git commit -m "feat: the workbench enters catalog-linked cards and lists them with status"`

---

### Task 10: 工作台的关系路由

**Files:**
- Create: `src/growbridge/workbench/evidence_relations.py`
- Modify: `src/growbridge/workbench/api.py`（在 `add_evidence_routes` 之后挂载）
- Test: `tests/workbench/test_workbench_evidence_relations.py`

**Interfaces:**
- Consumes: Task 5；`workbench/scope.py` 的 `project_read`。
- Produces:
  - `add_evidence_relation_routes(router, operator, archive, access=None)`
  - `POST /wb/evidence/relations`，请求体 `{kind, card_id, other_card_id?, reason}`：先用 `relation_scope` 算出关系所在的项目；有项目时调用 `project_read`；最后调用 `record_relation(..., viewer_project=那个项目)`。
  - `POST /wb/evidence/relations/{relation_id}/review`，请求体 `{decision: "confirmed"|"rejected", note: str = ""}`。
  - `POST /wb/evidence/relations/{relation_id}/withdraw`，请求体 `{reason}`（1–500 字）。
    - 审核和撤销这两条路由，都按关系的 `project_id` 或 `proposed_in` 调用 `project_read`。
  - `GET /wb/evidence/relations?project_id=`：返回 `records(project_id)`，并做两项过滤：
    - `proposed_in` 不为空、又不等于 `project_id` 的待确认提议，整条不列；
    - 已确认的模型提议，`proposed_in` 不等于 `project_id` 时，`reason` 改显示审核说明（设计 §6）。
    - 这条 GET 路由是本计划加的：设计 §5.7 要求证据页列出待确认关系，但没有写路由。
  - `RelationRefused` 转成 `Denied("state", …)`，做法同 Task 8。

- [ ] **Step 1: Write the failing tests**

```python
def test_an_operator_records_a_confirmed_relation(bench, client): ...
def test_review_and_withdraw_keep_the_first_record(bench, client): ...
def test_withdrawing_needs_a_reason(bench, client): ...
def test_confirming_a_model_proposal_between_public_cards_needs_a_note(bench, client): ...
def test_a_pending_proposal_of_project_p_is_not_listed_globally(bench, client): ...
def test_a_relation_with_another_users_project_card_is_hidden(bench, client): ...  # 多用户开启
def test_a_model_role_is_refused(bench, client): ...                                # model_role
```

- [ ] **Step 2–4:** `pytest tests/workbench/test_workbench_evidence_relations.py tests/workbench/test_console_known_codes.py -v`：先 FAIL，实现后 PASS。
- [ ] **Step 5: Commit** — `git commit -m "feat: workbench routes to record, review, withdraw and list evidence relations"`

---

### Task 11: 轮次结论转卡

**Files:**
- Create: `src/growbridge/research/round_cards.py`
- Modify: `src/growbridge/agents/memory_rounds.py`（把 `_invalid` 里收集快照的部分提取成公开函数 `report_snapshots`）
- Modify: `src/growbridge/workbench/evidence_relations.py`（加路由）
- Modify: `src/growbridge/workbench/api.py`（把 `workflow`、`holdout` 传进去）
- Test: `tests/research/test_round_cards.py`

**Interfaces:**
- Consumes:
  - `memory_rounds.load_report`；
  - `MemorySources`，在路由里构造：`book=None, notes=None, timezone="UTC", device_id=None, multi_user=access is not None`；
  - Task 1、2。
- Produces:
  - `report_snapshots(src: MemorySources, project_id: str, artifact: Any, body: dict) -> tuple[str, ...]`：`artifact.snapshot_id`（如果有），加上 `_own_snapshots` 的结果。`_invalid` 改为调用它。
  - `RoundCardInput(Model)`：`growth_stage: str = ""`、`conditions: tuple[ApplicabilityRange, ...] = ()`、`conditions_note: str = ""`、`value: float | None = None`、`unit: str | None = None`
  - `convert_round(src: MemorySources, catalog: Catalog, round_id: str, body: RoundCardInput, actor_id: str) -> EvidenceCard`
  - 路由 `POST /wb/rounds/{round_id}/evidence`：先按轮次所属的项目调用 `project_read`；返回 `{"card_id", "verified": True, "label"}`。

拒绝理由（用 `_register("state", ...)` 登记）：
- `round_card_not_delivered (round_id, state)`
- `round_card_report_unusable (round_id, problem)`，`problem` 是 `unavailable`、`invalid` 或 `held_out`
- `round_card_exists (round_id, card_id)`
- `round_card_no_conclusion (round_id)`
- 字段有问题时沿用 `evidence_card_invalid`。

卡片字段（设计 §5.4）：
- `source_class="local"`；
- `claim` 取报告的 `conclusion`，超过 1000 字时取前 999 字再加 `"…"`；
- `variable` = `catalog.current(protocol.analysis.primary_endpoint).id`；
- 有 `value` 时，`unit` 取该变量的目录单位；
- `crop_taxon`、`cultivar` 取自协议；`calibrated=True`；
- `citation` 的格式由实现者定。

写入：在同一个 `archive.db.transaction()` 里依次做两件事：
1. `archive.add_evidence(card, source=f"operator:{actor_id}", verified_by=actor_id)`；
2. `archive.ledger.add_origin(EvidenceOrigin(..., snapshot_ids=report_snapshots(...), label=artifact.label))`。

- [ ] **Step 1: Write the failing tests**（照 `tests/agents/test_memory_rounds.py` 造轮次和报告的方式）

```python
def test_a_delivered_round_becomes_a_verified_local_card(): ...
    # card.source_class == "local"，verified 为真，variable == 主要终点，crop_taxon == 协议的，origin.label == 报告的 label
def test_a_held_out_report_is_refused(): ...          # problem == "held_out"
def test_an_invalid_report_is_refused(): ...          # problem == "invalid"
def test_an_unfinished_round_is_refused(): ...        # round_card_not_delivered
def test_a_report_converts_once(): ...                # round_card_exists
def test_a_report_without_a_conclusion_is_refused(): ...   # Review Focus 4：缺失、"" 和 123 三种情况
def test_marking_the_snapshot_invalid_blocks_the_card(): ...
    # 转卡后调用 mark_dependents_invalid -> card_statuses(...)["ev"].validity == "dependency_invalid"，evidence_gate 挡住
def test_the_memory_downgrade_still_holds(): ...      # 现有的 test_memory_rounds 全部通过
```

- [ ] **Step 2–4:** `pytest tests/research/test_round_cards.py tests/agents/test_memory_rounds.py -v`：先 FAIL，实现后 PASS。
- [ ] **Step 5: Commit** — `git commit -m "feat: an operator turns a delivered round's conclusion into a project card"`

---

### Task 12: 日报的一行

**Files:**
- Modify: `src/growbridge/observer/report.py`（`ReportContext`、`render_daily_report`）
- Modify: `src/growbridge/runtime.py:507-514`
- Modify: `src/growbridge/planning/evidence_validity.py`（加 `report_stale_evidence`）
- Test: `tests/observer/test_report_evidence.py`

**Interfaces:**
- Consumes: `stale_evidence_lines`（Task 6）。
- Produces:
  - `ReportContext.stale_evidence: tuple[str, ...] = ()`；不为空时，在 "To do" 之前加一节 `_section("Evidence no longer valid", ...)`。
  - `report_stale_evidence(runtime: Any, stage: Any) -> tuple[str, ...]`：用 `runtime.workflow.stage(stage.stage_id).run_sheet` 和 `runtime.archive` 调用 `stale_evidence_lines`；出错时记日志并返回 `()`，做法照 `observer/episodes.py:279` 的 `report_recurring`。
  - `runtime.py` 的 `ReportContext(...)` 加 `stale_evidence=report_stale_evidence(self, stage)`；它的 import 和 Task 7 的 `evidence_gate` 合成一行。

- [ ] **Step 1: Write the failing tests**

```python
def test_the_section_appears_only_when_there_are_lines(): ...
    # stale_evidence=() 时报告里没有 "Evidence no longer valid"；有一行时，这一节出现在 "To do" 之前
def test_a_failure_leaves_the_section_out(): ...
```

- [ ] **Step 2–4:** `pytest tests/observer/test_report_evidence.py tests/test_runtime_size.py -v`：先 FAIL，实现后 PASS。
- [ ] **Step 5: Commit** — `git commit -m "feat: the daily report lists evidence a running stage cites that is no longer valid"`

---

### Task 13: 控制台

**Files:**
- Modify: `src/growbridge/web/workbench/pages/evidence.js`、`src/growbridge/web/workbench/pages/round.js`、`src/growbridge/web/workbench/i18n/{codes,messages}.{en,zh}.js`
- Test: `tests/web/evidence-page.test.mjs`（写法参照 `tests/web/research-pages.test.mjs`）

**Interfaces:**
- Consumes: Task 9–11 的路由与 JSON。
- Produces（设计 §5.7）：
  - **证据页**：
    - 顶部：项目选择（"全局"，以及用户能看到的项目），状态和变量两个筛选；
    - 每张卡：状态标记、替代卡链接、矛盾的卡、新字段；
    - 页面下方的关系列表：待确认的关系有"确认 / 驳回"，已确认的有"撤销"（必须写理由）；
    - "记录关系"表单：类型、另一张卡、理由。
  - **录卡表单**：
    - `variable` 下拉框只列标准编号，不含 `factor` 类；
    - 条件逐行填写变量、下限、上限，最多 8 行；
    - `crop_taxon`、`cultivar`、`growth_stage`、`conditions_note` 四个输入框；
    - 一行说明："轮次结论请从轮次页转卡"。
  - **轮次页**：已交付且报告可用的轮次显示"转为证据卡"按钮；不能转时显示原因，原因对应各条 `round_card_*` 拒绝理由。
  - **文案**：新代码的中英文文案，包括 10 个 finding 和 15 个 denial 理由（Task 5、8、11 登记的那些）。

- [ ] **Step 1: Write the failing tests**

```js
test("a superseded card shows its badge and links its replacement", ...);
test("a pending relation offers confirm and reject; a confirmed one offers withdraw", ...);
test("the variable picker lists no alias and no factor variable", ...);
test("the convert button shows only for a delivered round with a usable report", ...);
test("every new finding and denial code has copy in both languages", ...);
```

- [ ] **Step 2–4:** `node --test tests/web/*.test.mjs` 与 `pytest tests/workbench/test_console_known_codes.py -q`：先 FAIL，实现后 PASS。
- [ ] **Step 5: Commit** — `git commit -m "feat: console shows evidence status, relations and round-card conversion"`

---

### Task 14: 文档与剧本端到端

**Files:**
- Modify: `docs/wiki/{en,zh-CN}/API-Reference.md`（MCP 工具表加 `propose_evidence_relation`；更新证据段落和工作台路由）
- Modify: `docs/wiki/{en,zh-CN}/Data-Archive-and-Traceability.md`、`docs/wiki/{en,zh-CN}/The-Five-Agents.md`（凡是列出 `propose_evidence_card` 的地方）
- Test: `tests/e2e/test_e2e_evidence_validity.py`（照 `tests/e2e/test_e2e_memory.py` 的剧本模型写法）

- [ ] **Step 1: Write the failing e2e test**，按设计 §7 的剧本：
  1. 一条反馈规则引用手册卡 H；
  2. 剧本里的计划角色调用 `propose_evidence_relation(supersedes, card_id=Paper, other_card_id=H)`，操作员经路由确认；
  3. 下一次提交引用 H，返回的 findings 里有 `superseded_source`，且 `replacement_id == Paper`；
  4. 一个已在运行、引用 H 的阶段继续运行，当天日报里有 `"Evidence no longer valid"`；
  5. 一轮交付后经路由转卡，再用 `mark_dependents_invalid` 标记它的快照；之后提交引用这张卡的运行单，findings 里有 `dependency_invalid_source`。
- [ ] **Step 2: Run** `pytest tests/e2e/test_e2e_evidence_validity.py tests/docs -v`。各部件都已实现，e2e 应当直接通过；文档测试在改 wiki 之前会失败，因为 MCP 工具表里还没有新工具。
- [ ] **Step 3: Update the wiki pages**，中英文都改。
- [ ] **Step 4: Run** `pytest -q`、`ruff check src tests scripts`、`ruff format --check src tests scripts`、`node --test tests/web/*.test.mjs`，全部通过。
- [ ] **Step 5: Commit** — `git commit -m "docs: evidence relations and round cards in the wiki; scripted end-to-end test"`
