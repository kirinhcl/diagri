# Variable Catalog (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A shipped, append-only variable catalog that every metric name is checked and compared against:
- Protocols declare their variables.
- A manual measurement is refused unless it uses a declared catalog ID with that variable's exact unit.
- Every metric comparison goes through the catalog.
- Holdouts fail closed on names they cannot resolve.
- Snapshots record the variable definitions they used.
- The humidity rule also consults the catalog.

**Architecture:** A new `growbridge.vocab` package loads `catalog.toml` with stdlib `tomllib` into an immutable `Catalog`. `packaged_catalog()` caches the shipped file. Every consumer takes an optional `catalog` that defaults to it, so tests can inject `TEST_CATALOG` and the runtime loads the catalog once at startup. The protocol and entry rules are pure functions in `growbridge.vocab.checks`, which `WorkflowService` and the workbench call. `ResearchProtocol.variables` is left out of dumps when it is empty, so stored digests do not move.

**Tech Stack:** Python 3.11+, Pydantic 2 (`pydantic>=2,<3`), stdlib `tomllib`, SQLite via `growbridge.archive.db`, pytest with pytest-asyncio (auto mode), and the Node test runner for console scripts.

**Spec:** `docs/superpowers/specs/2026-11-17-variable-catalog-design.md`.
- This plan covers phase 1 (spec §1–10 and §12–14).
- It also fixes the `export.py` sensor-key bug from §11 (Task 8).
- Phase 2 (ontology `refs`, `crop_taxon`, export from `catalog.json`) gets its own plan after phase 1 ships, because its `refs` are filled by hand from OLS/AgroPortal.

## Global Constraints

- **Branch and worktree.** Work on branch `feat/variable-catalog` in a new worktree, `/Users/chenghao/Downloads/spiderfarmer-growbridge-vocab`, cut from `origin/main` (d7d479a or later). The main checkout is shared with another session that switches branches, so never edit files or run tests there.
- **Running tests.** Run them from the worktree with `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider`. This follows the other worktrees: `.venv` links to the main checkout's venv, whose editable install points elsewhere. Run console tests with `node --test tests/web/*.test.mjs`.
- **No new dependencies.** Read TOML with stdlib `tomllib`. Add no YAML, RDF or UCUM library.
- **Never use `Field(exclude_if=...)`**, because pyproject allows `pydantic>=2,<3`. To leave an empty field out of a dump, use `model_serializer(mode="wrap")`, as `ManualTask._without_unset_seconds` does (`archive/models.py:278-285`).
- **Stored data never changes.** No stored record and no stored protocol version is modified. A protocol without `variables` dumps exactly as it did before.
- **`resolve` is exact and case-sensitive.** It tries the id first, then aliases. No trimming, no lower-casing, no fuzzy matching. Only `kind = "sensor"` entries have aliases.
- **A broken catalog stops things.** A catalog that fails to load raises `CatalogError`. Nothing catches that error in order to skip a check.
- **Refusals list everything.** A refusal lists every problem at once and names the standard ID and unit to use.
- **Humidity only gets stricter.** The humidity check may only block more, never less.
- **Size limits.** `src/growbridge/runtime.py` is 793 lines and must stay ≤ 800 (`tests/test_runtime_size.py`). Other files stay ≤ 800 lines and functions < 50 lines.
- **Lint.** `ruff check src tests scripts` and `ruff format --check src tests scripts` must be clean. Console scripts never use `innerHTML` (`tests/web/no-html-injection.test.mjs`).
- **Commits.** Use the format `<type>: <description>`, with no attribution lines. Never run `git commit -n`.
- **Reading files.** Read in small chunks: grep first, then read 30–60 lines.

## Review Focus

1. **A metric with a stray space or different case** (`"canopy_area_growth "`, `"Canopy_area_growth"`), for example from a stale browser draft: it is refused, and the message lists the declared IDs (Task 5 test).
2. **An unresolved name in a development (non-held) batch:** it is kept. Failing closed applies only to held-out batches and to measurements without a batch (Task 4 test).
3. **A sample whose `data` has no `"sensor"` key** (device offline): `catalog.json` is still written, and that sample adds no sensor names (Task 6 test).
4. **A value exactly at `min` or `max`:** it is accepted, because the bounds are inclusive (Task 5 test).
5. **A protocol posted from the workbench JSON form without `variables`** (an old template or a saved draft): it is refused with a message that names `variables` (Task 2 test).

---

### Task 1: The catalog package

**Files:**
- Create: `src/growbridge/vocab/__init__.py`, `src/growbridge/vocab/catalog.py`, `src/growbridge/vocab/catalog.toml`, `src/growbridge/vocab/catalog.lock.json`
- Create: `tests/vocab_support.py`, `tests/vocab/test_vocab_catalog.py`, `tests/vocab/test_vocab_lock.py`
- Modify: `pyproject.toml` (`[tool.setuptools.package-data]`: add `"vocab/*.toml"`)

**Interfaces:**
- Produces, in `growbridge.vocab.catalog` and re-exported from `growbridge.vocab`:
  - `class CatalogError(ValueError)`
  - `QUANTITIES: frozenset[str]` = `temperature`, `relative_humidity`, `pressure`, `concentration`, `photon_flux_density`, `area_growth_rate`, `length`, `mass`, `level`, `count`, `score`
  - `DEFINING_FIELDS = ("id", "kind", "quantity", "unit", "method", "min", "max")`
  - `class Variable(Model)`. Here `Model` is `growbridge.archive.models.Model`, which is frozen and forbids extra fields. Fields:
    - `id: str`
    - `kind: Literal["manual", "sensor", "factor"]`
    - `label_en: str`
    - `label_zh: str`
    - `quantity: str`
    - `unit: str`
    - `method: str = ""`
    - `min: float | None = None`
    - `max: float | None = None`
    - `aliases: tuple[str, ...] = ()`
    - `deprecated: bool = False`
    - `replaced_by: str | None = None`
    - `refs: tuple[str, ...] = ()`

    Method `defining_digest() -> str` returns the `content_digest` of `{name: value}` over `DEFINING_FIELDS`.
  - `class Catalog`, immutable.
    - Attributes:
      - `version: int`
      - `digest: str`: the sha256 hex of the TOML text's UTF-8 bytes
      - `unit_aliases: Mapping[str, str]`
      - `variables: tuple[Variable, ...]`, sorted by id
    - Methods:
      - `get(variable_id: str) -> Variable | None` matches the id only.
      - `resolve(name: str) -> Variable | None` tries the id, then aliases.
      - `canonical(name: str) -> str | None`
      - `same(a: str, b: str) -> bool` is true when both names resolve to one id, or when neither resolves and `a == b`.
  - `load_catalog(text: str) -> Catalog`
  - `packaged_text() -> str`, which reads the file via `importlib.resources.files("growbridge.vocab")`
  - `packaged_catalog() -> Catalog`, wrapped in `functools.cache`. It must look up the module-level `packaged_text()` at call time.
- Produces, in `tests/vocab_support.py`:
  - `TEST_ENTRIES: str` adds four manual entries, each with a short method: `height` (length, `cm`), `yield_g` (mass, `g`), `yield` (mass, `g`) and `canopy_score` (score, `{score}`). These are the names existing tests use.
  - `TEST_CATALOG = load_catalog(packaged_text() + TEST_ENTRIES)`

- [ ] **Step 1: Create the worktree and commit the docs**

```bash
cd /Users/chenghao/Downloads/spiderfarmer-growbridge
git fetch origin main
git worktree add -b feat/variable-catalog ../spiderfarmer-growbridge-vocab origin/main
cp docs/superpowers/specs/2026-11-17-variable-catalog-design.md ../spiderfarmer-growbridge-vocab/docs/superpowers/specs/
cp docs/superpowers/plans/2026-11-17-variable-catalog.md ../spiderfarmer-growbridge-vocab/docs/superpowers/plans/
cd ../spiderfarmer-growbridge-vocab
ln -s ../spiderfarmer-growbridge/.venv .venv
git add docs/superpowers && git commit -m "docs: add the variable catalog design and plan"
```

- [ ] **Step 2: Write the failing tests in `tests/vocab/test_vocab_catalog.py`**

```python
import pytest

from growbridge.control.device import SENSORS
from growbridge.vocab import CatalogError, load_catalog, packaged_catalog

BASE = """version = 1
[[variable]]
id = "leaf_count"
kind = "manual"
label_en = "Leaf count"
label_zh = "叶片数"
quantity = "count"
unit = "1"
method = "counted by hand"
min = 0
"""
ENTRY = BASE.removeprefix("version = 1\n")
SENSOR = """
[[variable]]
id = "leaf_wetness"
kind = "sensor"
label_en = "Leaf wetness"
label_zh = "叶面湿润度"
quantity = "level"
unit = "%"
aliases = ["wet"]
"""
BROKEN = {  # case -> (text, a name the message must contain)
    "duplicate id": (BASE + ENTRY, "leaf_count"),
    "bad id": (BASE.replace('"leaf_count"', '"Leaf-Count"'), "Leaf-Count"),
    "unknown kind": (BASE.replace('"manual"', '"derived"'), "leaf_count"),
    "unknown quantity": (BASE.replace('"count"', '"amount"'), "leaf_count"),
    "manual without method": (BASE.replace('method = "counted by hand"\n', ""), "leaf_count"),
    "alias on a manual entry": (BASE + 'aliases = ["leaves"]\n', "leaf_count"),
    "min above max": (BASE + "max = -1\n", "leaf_count"),
    "dangling replaced_by": (BASE + 'deprecated = true\nreplaced_by = "gone"\n', "leaf_count"),
    "alias equals an id": (BASE + SENSOR.replace('["wet"]', '["leaf_count"]'), "leaf_count"),
    "duplicate alias": (BASE + SENSOR + SENSOR.replace("leaf_wetness", "leaf_wet_2"), "wet"),
}


def test_packaged_catalog_loads():
    catalog = packaged_catalog()
    assert catalog.version >= 1
    assert len(catalog.digest) == 64


def test_every_device_sensor_resolves_with_its_unit():
    catalog = packaged_catalog()
    for key, unit in SENSORS.items():
        variable = catalog.resolve(key)
        assert variable is not None and variable.kind == "sensor", key
        assert catalog.unit_aliases.get(unit, unit) == variable.unit, key


def test_fixture_names_are_catalogued():
    catalog = packaged_catalog()
    assert catalog.get("canopy_area_growth").kind == "manual"
    assert catalog.get("canopy_area_growth").unit == "cm2/d"
    assert catalog.get("light").kind == "factor"


def test_resolve_is_exact():
    catalog = packaged_catalog()
    assert catalog.resolve("temp").id == "air_temperature"
    assert catalog.resolve("air_temperature").id == "air_temperature"
    for near in ("Temp", "temp ", "air-temperature", ""):
        assert catalog.resolve(near) is None
    assert catalog.get("temp") is None  # get never follows an alias


def test_same_compares_ids_and_unresolved_strings():
    catalog = packaged_catalog()
    assert catalog.same("temp", "air_temperature")
    assert catalog.same("heigth", "heigth")
    assert not catalog.same("heigth", "height")
    assert not catalog.same("temp", "heigth")


def test_deprecated_entry_resolves_to_itself():
    old = ENTRY.replace("leaf_count", "leaf_number")
    catalog = load_catalog(BASE + old + 'deprecated = true\nreplaced_by = "leaf_count"\n')
    assert catalog.resolve("leaf_number").id == "leaf_number"


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_broken_catalog_names_the_entry(case):
    text, name = BROKEN[case]
    with pytest.raises(CatalogError, match=name):
        load_catalog(text)


def test_text_that_is_not_toml_is_refused():
    with pytest.raises(CatalogError):
        load_catalog("version = [")
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/vocab/test_vocab_catalog.py`
Expected: a collection error, `ModuleNotFoundError: No module named 'growbridge.vocab'`

- [ ] **Step 4: Write `src/growbridge/vocab/catalog.toml`**

Start the file with `version = 1` and a `[unit_aliases]` table holding `C = "Cel"` and `ppm = "[ppm]"`. Then add these entries:

| id | kind | quantity | unit | aliases | fixed values |
|---|---|---|---|---|---|
| `air_temperature` | sensor | temperature | `Cel` | `temp` | |
| `air_relative_humidity` | sensor | relative_humidity | `%` | `humi` | min 0, max 100 |
| `vapour_pressure_deficit` | sensor | pressure | `kPa` | `vpd` | min 0 |
| `co2_concentration` | sensor | concentration | `[ppm]` | `co2` | min 0 |
| `photosynthetic_photon_flux_density` | sensor | photon_flux_density | `umol/m2/s` | `ppfd` | min 0 |
| `soil_temperature` | sensor | temperature | `Cel` | `tempSoil` | |
| `canopy_area_growth` | manual | area_growth_rate | `cm2/d` | | method `"Canopy area from top-view images, change per day"` |
| `light` | factor | level | `%` | | min 0, max 100 |

Every entry gets `refs = []`. Choose the labels yourself, and any `min`/`max` the table leaves blank.

- [ ] **Step 5: Implement `src/growbridge/vocab/catalog.py` and `__init__.py`**

`load_catalog` works like this:
- It parses the text with `tomllib.loads`. A `TOMLDecodeError` becomes a `CatalogError`.
- It builds each entry with `Variable.model_validate`. A validation error becomes a `CatalogError` whose message names the entry's id.
- It then enforces the rules below. Every message names the offending id or alias:
  - the id matches `^[a-z][a-z0-9_]{1,62}$`
  - ids are unique
  - `quantity` is in `QUANTITIES`
  - a `manual` entry has a `method`
  - only `sensor` entries have aliases
  - aliases are unique and never equal an id
  - `replaced_by` names an existing entry and appears only with `deprecated = true`
  - `min ≤ max`
  - `version` is a positive int

- [ ] **Step 6: Run the tests to see them pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/vocab/test_vocab_catalog.py`
Expected: all pass

- [ ] **Step 7: Write the lock tests in `tests/vocab/test_vocab_lock.py`**

```python
import json
import tomllib
from pathlib import Path

import growbridge.vocab
from growbridge.vocab import packaged_catalog

LOCK = Path(growbridge.vocab.__file__).with_name("catalog.lock.json")
PYPROJECT = Path(__file__).parents[2] / "pyproject.toml"


def test_catalog_version_is_locked():
    lock, catalog = json.loads(LOCK.read_text()), packaged_catalog()
    assert lock["versions"].get(str(catalog.version)) == catalog.digest, (
        "catalog.toml changed: bump `version` and add "
        f'"{catalog.version}": "{catalog.digest}" to "versions" in catalog.lock.json'
    )
    assert len(set(lock["versions"].values())) == len(lock["versions"])


def test_defining_fields_never_change():
    entries, catalog = json.loads(LOCK.read_text())["entries"], packaged_catalog()
    for variable in catalog.variables:
        expected = variable.defining_digest()
        assert entries.get(variable.id) == expected, (
            f'{variable.id}: add "{variable.id}": "{expected}" to "entries" if it is new; '
            "an existing entry's id, kind, quantity, unit, method, min and max never change"
        )
    assert set(entries) <= {v.id for v in catalog.variables}, "entries are never removed"


def test_catalog_ships_with_the_package():
    config = tomllib.loads(PYPROJECT.read_text())
    assert "vocab/*.toml" in config["tool"]["setuptools"]["package-data"]["growbridge"]
```

- [ ] **Step 8: Write the lock file, package data and test catalog**

- Write `catalog.lock.json` as `{"versions": {"1": "<digest>"}, "entries": {"<id>": "<defining digest>", ...}}`, filled in from `packaged_catalog()`.
- Add `"vocab/*.toml"` to package-data.
- Write `tests/vocab_support.py` as described under Interfaces.

- [ ] **Step 9: Run the vocab tests and lint**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/vocab && .venv/bin/ruff check src tests && .venv/bin/ruff format --check src tests`
Expected: all pass and the lint is clean

- [ ] **Step 10: Commit**

```bash
git add src/growbridge/vocab pyproject.toml tests/vocab tests/vocab_support.py
git commit -m "feat: add the append-only variable catalog"
```

---

### Task 2: Protocols declare their variables

**Files:**
- Create: `src/growbridge/vocab/checks.py`, `tests/vocab/test_vocab_protocol.py`
- Modify:
  - `src/growbridge/archive/models.py` (`ResearchProtocol`, line 422)
  - `src/growbridge/workflow/store.py` (next to `protocol`, line 145)
  - `src/growbridge/workflow/service.py` (`__init__` at 78, `save_protocol` at 108)
  - `src/growbridge/sim/fixtures.py` (`make_protocol`, line 102)
  - `src/growbridge/web/workbench/pages/project-forms.js` (`protocolExample`)
  - `tests/vocab_support.py` (add `OLD_ENTRY`, `WITH_OLD`)
- Test: `tests/workflow/test_workflow_design.py`, `tests/workbench/test_workbench_rounds.py`

**Interfaces:**
- Consumes: `Catalog.get`, `Catalog.resolve`, `load_catalog`, `packaged_text` (Task 1).
- Produces:
  - `ResearchProtocol.variables: tuple[str, ...] = ()`, plus `@model_serializer(mode="wrap") def _without_empty_variables(self, handler)`, which pops `"variables"` from the dump when it is empty.
  - `check_protocol(protocol: ResearchProtocol, catalog: Catalog, declared_before: frozenset[str]) -> list[str]` in `growbridge.vocab.checks`.
  - `WorkflowStore.protocol_variables_before(protocol_id: str, version: int) -> frozenset[str]`: the union of `variables` over the saved versions of `protocol_id` below `version`.
  - `WorkflowService.__init__(..., catalog: Catalog | None = None)`, which sets `self.catalog = catalog or packaged_catalog()`. Tasks 3, 5 and 6 read this as `deps.workflow.catalog` or `self.workflow.catalog`.
  - `make_protocol()` defaults to `variables=("canopy_area_growth",)`.
  - In `tests/vocab_support.py`, `WITH_OLD = load_catalog(packaged_text() + OLD_ENTRY)`. `OLD_ENTRY` is the manual entry `canopy_growth_old` (quantity `area_growth_rate`, unit `cm2/d`, method `"old method"`) with `deprecated = true` and `replaced_by = "canopy_area_growth"`. Task 5 uses it too.

- [ ] **Step 1: Write the failing tests in `tests/vocab/test_vocab_protocol.py`**

```python
from vocab_support import WITH_OLD

from growbridge.archive.ids import content_digest
from growbridge.archive.models import ResearchProtocol, Treatment
from growbridge.sim.fixtures import make_protocol
from growbridge.vocab import packaged_catalog
from growbridge.vocab.checks import check_protocol

NONE = frozenset()


def test_protocol_without_variables_dumps_as_before():
    raw = make_protocol(variables=()).model_dump(mode="json")
    assert "variables" not in raw
    assert ResearchProtocol.model_validate(raw).digest() == content_digest(raw)


def test_declared_variables_are_dumped():
    assert make_protocol().model_dump(mode="json")["variables"] == ["canopy_area_growth"]


def test_fixture_protocol_passes():
    assert check_protocol(make_protocol(), packaged_catalog(), NONE) == []


def test_every_problem_is_reported_at_once():
    protocol = make_protocol(
        variables=("canopy_area_growth", "canopy_area_growth", "temp", "heigth"),
        treatments=(
            Treatment(id="control", name="c", factors={"lux": 40}),
            Treatment(id="high", name="h", factors={"light": 70}),
        ),
    )
    problems = " | ".join(check_protocol(protocol, packaged_catalog(), NONE))
    assert "twice" in problems
    assert "air_temperature" in problems  # an alias names the ID to use
    assert "heigth" in problems
    assert "lux" in problems


def test_empty_variables_are_refused():
    problems = check_protocol(make_protocol(variables=()), packaged_catalog(), NONE)
    assert any("variables" in p for p in problems)


def test_endpoint_must_be_declared():
    problems = check_protocol(make_protocol(variables=("light",)), packaged_catalog(), NONE)
    assert any("canopy_area_growth" in p for p in problems)


def test_deprecated_variable_needs_an_earlier_declaration():
    protocol = make_protocol(variables=("canopy_area_growth", "canopy_growth_old"))
    refused = check_protocol(protocol, WITH_OLD, NONE)
    assert any("canopy_growth_old" in p and "canopy_area_growth" in p for p in refused)
    assert check_protocol(protocol, WITH_OLD, frozenset({"canopy_growth_old"})) == []
```

Then add tests in two other files.

In `tests/workflow/test_workflow_design.py`, using that file's service fixture:
- `test_save_protocol_refuses_undeclared_variables`: `save_protocol(make_protocol(variables=()), designer)` raises `Denied` with code `"param"`.
- `test_saving_the_same_stored_version_skips_the_checks`: store `make_protocol(variables=())` directly with `service.store.put_protocol(protocol, 0.0)`. Then `save_protocol` of that same protocol returns it without raising.
- `test_new_version_may_keep_a_deprecated_variable`: build the service with `catalog=WITH_OLD`.
  - Store v1, which declares `canopy_growth_old`, directly with `put_protocol`.
  - Saving v2 with the same variables succeeds.
  - Saving a protocol with another id and the same variables is refused.

In `tests/workbench/test_workbench_rounds.py` (Review Focus 5):
- `test_protocol_without_variables_is_refused_by_name`: post the file's protocol body with `"variables"` removed to `/wb/protocols`. Assert that `response.json()["detail"]["code"] == "param"` and that `"variables"` is in `response.json()["detail"]["message"]`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/vocab/test_vocab_protocol.py`
Expected: FAIL, because `ResearchProtocol` rejects `variables` as an extra field (`extra_forbidden`)

- [ ] **Step 3: Add the field and its serializer**

In `archive/models.py`, add the field after `experimental_unit`. Add the serializer modelled on `ManualTask._without_unset_seconds`, with a comment explaining why: protocols saved before the field existed must keep their digest.

- [ ] **Step 4: Implement `check_protocol`**

Apply spec §6 rules 1–5, and return every problem found:
- A name that only resolves through an alias is refused, and the message names the standard ID.
- A deprecated ID is accepted only if it is in `declared_before`. Otherwise the message names its `replaced_by`.
- Every factor key must be the ID of a `kind == "factor"` entry.

- [ ] **Step 5: Wire it into the store and service, and update the fixtures**

- `protocol_variables_before`: one query on `wf_protocols` with `id = ? AND version < ?`, returning the union of each body's `variables`.
- `WorkflowService`:
  - Add the `catalog` parameter to `__init__`.
  - In `save_protocol`, when `saved is None`, call `check_protocol(protocol, self.catalog, self.store.protocol_variables_before(protocol.id, protocol.version))`. If it returns problems, raise `Denied("param", "; ".join(problems))`.
  - When an identical version already exists, keep returning it without checking.
- `make_protocol` gets `variables=("canopy_area_growth",)`.
- `protocolExample` gets `variables: ["canopy_area_growth"]`, placed before `analysis`.

- [ ] **Step 6: Run the whole suite and fix fixture protocols**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider && node --test tests/web/*.test.mjs`
Expected: all pass.

Tests that post or build protocol bodies without `variables` now fail with a message asking to declare the protocol's variables. Fix each one by adding `"variables": ["canopy_area_growth"]` to its body. Expect failures in:
- `tests/workbench/test_workbench_rounds.py`
- `tests/workbench/test_workbench_names.py`
- `tests/workflow/*`
- `tests/e2e/*`

Do not weaken any assertion.

- [ ] **Step 7: Commit**

```bash
git add -A src tests
git commit -m "feat: protocols declare their variables from the catalog"
```

---

### Task 3: Statistics, reports and previews compare by ID

**Files:**
- Modify:
  - `src/growbridge/research/stats.py` (`UnitTable` line 49, `unit_table` line 55, `unit_means`)
  - `src/growbridge/agents/handlers_report.py` (`_data_rounds` 136, `_missing_fraction` 151, `_table` 404, notes at 480)
  - `src/growbridge/research/notes.py` (`TEMPLATES`)
  - `src/growbridge/archive/snapshot.py` (`preview`, grouping at 246-248)
- Test:
  - `tests/research/test_research_stats.py`
  - `tests/research/test_research_notes.py`
  - `tests/archive/test_archive_snapshot.py`
  - the report-publishing test in `tests/dispatch/`

**Interfaces:**
- Consumes: `Catalog.same`, `Catalog.canonical`, `Catalog.resolve` (Task 1); `WorkflowService.catalog` (Task 2).
- Produces:
  - `UnitTable.unresolved: tuple[str, ...] = ()`: the ids of input measurements whose metric does not resolve, not counting measurements that have been corrected.
  - `unit_table(..., failed_rounds=(), catalog: Catalog | None = None)`; `unit_means` passes `catalog` through.
  - `preview(..., catalog: Catalog | None = None)`.
  - A note with code `"unresolved_metrics"` and param `count`.

- [ ] **Step 1: Write the failing tests**

In `tests/research/test_research_stats.py`, use the file's `measurement(index, experiment, plant, value, **extra)` helper. Use the allocations and round map that its other tests use, referred to below as `ALLOCATIONS` and `ROUND_OF`.

```python
def test_alias_and_id_give_the_same_table():
    by_alias = [measurement(0, "e1", "p1", 1.0, metric="temp", unit="Cel"),
                measurement(1, "e1", "p2", 3.0, metric="air_temperature", unit="Cel")]
    by_id = [m.model_copy(update={"metric": "air_temperature"}) for m in by_alias]
    table = unit_table(by_alias, ALLOCATIONS, "air_temperature", ROUND_OF)
    assert table.values == unit_table(by_id, ALLOCATIONS, "air_temperature", ROUND_OF).values
    assert table.unresolved == ()


def test_unresolved_names_never_merge_and_are_counted():
    rows = [measurement(0, "e1", "p1", 1.0, metric="height"),
            measurement(1, "e1", "p2", 9.0, metric="heigth")]
    table = unit_table(rows, ALLOCATIONS, "height", ROUND_OF)
    assert table.unresolved == (rows[0].id, rows[1].id)
    assert table.values == unit_table(rows[:1], ALLOCATIONS, "height", ROUND_OF).values
```

Then add these tests in the other files:
- `tests/research/test_research_notes.py`: `test_unresolved_metrics_note_has_both_languages` checks that `note("unresolved_metrics", count=2)` renders in both `en` and `zh` and includes `2`.
- `tests/archive/test_archive_snapshot.py` (preview tests): `test_preview_groups_alias_with_id` checks that measurements named `temp` and `air_temperature` appear in one `air_temperature` group, and that a `heigth` measurement has its own group.
- The dispatch report-publishing test: copy it, add one `heigth` measurement to the snapshot, and assert that the published notes include code `unresolved_metrics` with `count == 1`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/research/test_research_stats.py tests/research/test_research_notes.py`
Expected: FAIL, because `UnitTable` has no attribute `unresolved` and the note code is unknown

- [ ] **Step 3: Implement**

- `unit_table`:
  - Select rows with `catalog.same(item.metric, metric)`.
  - Fill `unresolved` from the non-corrected rows where `catalog.resolve(item.metric) is None`.
  - Leave the mixed-unit `ValueError` unchanged.
- `handlers_report.py`:
  - `_data_rounds` and `_missing_fraction` take the catalog and compare with `same`.
  - `_table` passes `deps.workflow.catalog`.
  - `publish` adds `note("unresolved_metrics", count=len(table.unresolved))` when the count is non-zero, the same way it adds `unallocated_measurements`.
- Note template:
  - en: `"{count} measurements name a metric the variable catalog does not know; check them for misspellings"`
  - zh: `"{count} 条测量的指标名不在变量目录里，请检查是否拼错"`
- `preview` groups by `catalog.canonical(m.metric) or m.metric`.

- [ ] **Step 4: Run the tests to see them pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/research tests/archive tests/dispatch`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "feat: compare metric names through the variable catalog"
```

---

### Task 4: Holdouts fail closed on names they cannot resolve

**Files:**
- Modify:
  - `src/growbridge/research/holdout.py` (`OutcomeSource` 56, `_ProjectOutcomes` 64, `project_outcomes` 92, `HoldoutRegistry.__init__` 123, `register` 129, `keep` 211)
  - `src/growbridge/archive/store.py` (replace `outcome_experiments`, lines 352-370)
  - `src/growbridge/runtime.py` (the `project_outcomes(...)` call)
  - `tests/workbench/workbench_support.py`
- Move: `tests/archive/test_archive_outcome_experiments.py` → `tests/archive/test_archive_batch_metrics.py`
- Test:
  - `tests/research/test_research_holdout.py`
  - `tests/research/test_research_holdout_registration.py`
  - The dispatch tests that build `HoldoutRegistry(env.db, env.clock)`: `test_dispatch_snapshot_scope.py:200`, `test_dispatch_planner_holdout.py:30`, `test_dispatch_report_frozen.py:212`, `test_dispatch_researcher.py:772`. Where they register test names, they pass `catalog=TEST_CATALOG`.

**Interfaces:**
- Consumes: `Catalog.canonical`, `TEST_CATALOG` (Task 1).
- Produces:
  - `Archive.batch_metrics(batch_ids: Sequence[str]) -> tuple[tuple[str, str], ...]`:
    - Returns the distinct `(experiment_id, metric)` pairs of measurements whose batch is in `batch_ids` or is empty, sorted.
    - Includes corrected records and corrections.
    - Filters in SQL with `json_each`, as the current code does.
    - It replaces `outcome_experiments`, which is removed.
  - `OutcomeSource.existing_outcomes(project_id, batch_ids, outcome_fields) -> tuple[str, ...]`:
    - Returns the sorted, distinct raw metric names that count as existing outcome data in the project.
    - A name counts if it resolves to one of the outcome fields' IDs, or if it resolves to nothing.
    - The ownership rule is unchanged.
    - It replaces `has_outcomes`.
  - `project_outcomes(matching: Callable[[Collection[str]], Iterable[tuple[str, str]]], owners_of, catalog: Catalog | None = None) -> OutcomeSource`.
  - `HoldoutRegistry(db, clock, outcomes=None, catalog: Catalog | None = None)`, with a `catalog` attribute.
  - `register` raises:
    - `Denied("param", ...)` naming every outcome field that does not resolve.
    - `Denied("state", <current message> + ": " + names)` when `existing_outcomes` is non-empty.
  - `keep`. Its body is given here because the signature does not determine it:

```python
def keep(measurement: ManualMeasurement) -> bool:
    name = catalog.canonical(measurement.metric)  # None: unknown, so treated as an outcome
    for row in rows_of_project:
        fields = {catalog.canonical(f) for f in json.loads(row["outcome_fields"])}
        if name is not None and name not in fields:
            continue
        if not measurement.batch or measurement.batch in json.loads(row["batch_ids"]):
            return False
    return True
```

- [ ] **Step 1: Write the failing tests**

In `tests/research/test_research_holdout.py`:
- Use the file's `measurement(metric, batch)` helper.
- Set up a `registry` fixture: adapt the file's registry helper (line 28) to build with `catalog=TEST_CATALOG`, then register holdout `h1` for project `p1`:
  - held-out batch `b3`
  - outcome `["yield_g"]`
  - the file's development batches (`b1`, `b2`, … as many as `MIN_DEVELOPMENT_BATCHES` needs)

```python
def test_misspelled_outcome_in_held_batch_is_hidden(registry):  # it leaked before
    assert registry.development_filter("p1")(measurement("yeild_g", "b3")) is False


def test_unresolved_name_in_development_batch_is_kept(registry):  # Review Focus 2
    assert registry.development_filter("p1")(measurement("yeild_g", "b1")) is True


def test_other_known_metric_in_held_batch_is_kept(registry):
    assert registry.development_filter("p1")(measurement("height", "b3")) is True


def test_snapshot_with_unresolved_held_row_is_refused(registry, tmp_path):
    rows = tmp_path / "measurements.jsonl"
    rows.write_text(measurement("yeild_g", "b3").model_dump_json() + "\n")
    with pytest.raises(Denied):
        refuse_holdout_rows(registry, "p1", "snap-1", rows)
```

In `tests/research/test_research_holdout_registration.py`:
- Rewrite each `has_outcomes` case as an `existing_outcomes` case, keeping the same ownership expectations. Where the old test expected `True`, expect a non-empty tuple; where it expected `False`, expect `()`.
- Then add these tests. `DEV` is the file's development batches.

```python
def test_unresolved_existing_name_counts_as_an_outcome():
    source = project_outcomes(lambda b: [("exp-1", "yeild_g")], lambda e: ("p1",), TEST_CATALOG)
    assert source.existing_outcomes("p1", ("b3",), ("yield_g",)) == ("yeild_g",)


def test_outcome_fields_must_resolve(db, clock):
    registry = HoldoutRegistry(db, clock, catalog=TEST_CATALOG)
    with pytest.raises(Denied, match="yeild_g") as refused:
        registry.register("p1", "h1", ["b3"], ["yeild_g"], DEV)
    assert refused.value.code == "param"


def test_refusal_lists_the_names_that_block_registration(db, clock):
    source = project_outcomes(lambda b: [("exp-1", "yeild_g")], lambda e: ("p1",), TEST_CATALOG)
    registry = HoldoutRegistry(db, clock, source, TEST_CATALOG)
    with pytest.raises(Denied, match="yeild_g"):
        registry.register("p1", "h1", ["b3"], ["yield_g"], DEV)
```

In `tests/archive/test_archive_batch_metrics.py`, port each `outcome_experiments` case to `batch_metrics`, with pairs as the expected values:
- a batch match
- an empty batch matching
- corrected records included
- a quoted name
- empty input → `()`

- [ ] **Step 2: Run the tests to see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/research/test_research_holdout.py tests/research/test_research_holdout_registration.py tests/archive/test_archive_batch_metrics.py`
Expected: FAIL, because `catalog` is an unexpected keyword, and `batch_metrics` and `existing_outcomes` do not exist

- [ ] **Step 3: Implement**

- Add `batch_metrics`, `existing_outcomes`, the registry's `catalog`, the two `register` refusals, and `keep` as given above.
- In `runtime.py`, pass `archive.batch_metrics`.
- In `workbench_support.py`, `Bench` builds `project_outcomes(self.archive.batch_metrics, ..., TEST_CATALOG)` and `HoldoutRegistry(self.db, self.clock, outcomes, TEST_CATALOG)`.
- Update the docstrings of `development_filter` and `existing_outcomes` to say that unknown names count as outcomes.

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider`
Expected: all pass. Where a test registers a name that is not in the packaged catalog, inject `TEST_CATALOG`; do not rename the metric.

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "feat: holdouts fail closed on metric names they cannot resolve"
```

---

### Task 5: Measurement entry checks and the variable dropdown

**Files:**
- Modify:
  - `src/growbridge/vocab/checks.py`
  - `src/growbridge/workflow/store.py` (next to `protocol_versions_of`, line 369)
  - `src/growbridge/workbench/api.py` (`POST /measurements` at 458; a new read route in `_read_routes`)
  - `src/growbridge/web/workbench/pages/stage-measurements.js`
  - `src/growbridge/web/workbench/pages/stage.js` (line 259)
  - `src/growbridge/web/workbench/i18n/en.js`, `zh.js`
  - `tests/workbench/workbench_support.py`
  - `tests/e2e/*.py` (unit spelling)
- Create: `tests/vocab/test_vocab_entry.py`, `tests/workbench/test_workbench_variables.py`
- Test: `tests/web/measurements.test.mjs`

**Interfaces:**
- Consumes: `Catalog.get`, `load_catalog`, `packaged_text` (Task 1); `WorkflowService.catalog`, `ResearchProtocol.variables`, `vocab_support.WITH_OLD` (Task 2).
- Produces:
  - `check_measurement(record: ManualMeasurement, catalog: Catalog, declared: frozenset[str]) -> list[str]` in `growbridge.vocab.checks`.
  - `WorkflowStore.declared_variables(experiment_id: str) -> frozenset[str]`: the union of `variables` over `protocol_versions_of(experiment_id)`. Task 6 uses it.
  - `GET /wb/experiments/{experiment_id}/variables`:
    - Returns `{"experiment_id": ..., "variables": [{"id", "label_en", "label_zh", "unit", "method", "min", "max", "deprecated"}]}`, sorted by id.
    - Refuses `Denied("scope", ...)` for an experiment that no stage runs, the same rule `POST /measurements` applies.
  - JS exports from `stage-measurements.js`:
    - `variableOptions(variables, lang) -> [{value, label}]`. The label is `label_zh` when `lang === "zh"` and `label_en` otherwise, followed by ` (<unit>)`.
    - `measurementBody(values, variables, experimentId) -> object`: the body to post, with `unit` taken from the chosen variable.
    - `measurementForm(ctx, stage, onRecorded, variables)`.

- [ ] **Step 1: Write the failing tests in `tests/vocab/test_vocab_entry.py`**

```python
from vocab_support import WITH_OLD

from growbridge.archive.models import ManualMeasurement
from growbridge.vocab import load_catalog, packaged_text
from growbridge.vocab.checks import check_measurement

FIELDS = dict(id="m-2", experiment_id="e1", batch="b1", plant_id="p1", layout_version="v1",
              measured_at=1.0, position="tent-1", method="m", operator="op")
DECLARED = frozenset({"canopy_area_growth", "canopy_growth_old", "light"})
BOUNDED = """
[[variable]]
id = "leaf_cover"
kind = "manual"
label_en = "Leaf cover"
label_zh = "叶面覆盖"
quantity = "level"
unit = "%"
method = "grid count"
min = 0
max = 100
"""


def record(metric, unit, value):
    return ManualMeasurement(**FIELDS, metric=metric, unit=unit, value=value)


def test_declared_manual_metric_in_its_unit_passes():
    assert check_measurement(record("canopy_area_growth", "cm2/d", 3.0), WITH_OLD, DECLARED) == []


def test_experiment_without_declared_variables_is_refused():
    (problem,) = check_measurement(record("canopy_area_growth", "cm2/d", 3.0), WITH_OLD, frozenset())
    assert "declares no variables" in problem


def test_near_names_are_refused_with_the_declared_ids():  # Review Focus 1
    for near in ("canopy_area_growth ", "Canopy_area_growth", "canopy-area-growth"):
        (problem,) = check_measurement(record(near, "cm2/d", 3.0), WITH_OLD, DECLARED)
        assert "canopy_area_growth" in problem and "light" in problem


def test_kind_unit_and_bounds_are_reported_together():
    problems = check_measurement(record("light", "lux", -5.0), WITH_OLD, DECLARED)
    assert len(problems) == 3
    assert any("%" in p for p in problems)


def test_bounds_are_inclusive():  # Review Focus 4
    bounded = load_catalog(packaged_text() + BOUNDED)
    for value in (0.0, 100.0):
        assert check_measurement(record("leaf_cover", "%", value), bounded, frozenset({"leaf_cover"})) == []


def test_declared_deprecated_variable_is_accepted():
    assert check_measurement(record("canopy_growth_old", "cm2/d", 1.0), WITH_OLD, DECLARED) == []


def test_correction_may_change_the_metric():
    fixed = record("canopy_area_growth", "cm2/d", 2.0).model_copy(update={"corrects": "m-1"})
    assert check_measurement(fixed, WITH_OLD, DECLARED) == []
```

Then add tests in two more files.

In `tests/workbench/test_workbench_variables.py`, using the `Bench` fixtures:
- `test_undeclared_metric_is_refused_with_422`: posting metric `"heigth"` returns 422 with `detail.code == "param"` and `"height"` in the message, and nothing is stored.
- `test_wrong_unit_is_refused`: posting `height` in `"mm"` returns 422 with `"cm"` in the message.
- `test_variables_endpoint_lists_declared_variables`: GET `/wb/experiments/experiment-stage-1/variables` lists ids `["canopy_area_growth", "height", "yield_g"]`, each with its unit and method.
- `test_variables_endpoint_refuses_unknown_experiment`: for an unknown experiment, the status matches what `POST /measurements` returns for that experiment.
- `test_union_over_protocol_versions`: a second round on protocol v2 declares `canopy_score`; after that, both `height` and `canopy_score` are accepted.

In `tests/web/measurements.test.mjs`:
- `variableOptions` with `"zh"` gives `label_zh (unit)`; with `"en"` it gives `label_en (unit)`.
- `measurementBody` takes `unit` from the chosen variable even when `values.unit` holds something else.
- The form built with `variables = []` has no submit button and shows `measure.noVariables`.
- `measurementOptions` now returns only `method`.

- [ ] **Step 2: Run the tests to see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/vocab/test_vocab_entry.py tests/workbench/test_workbench_variables.py; node --test tests/web/measurements.test.mjs`
Expected: FAIL. Importing `check_measurement` raises an ImportError, the route is missing, and the JS exports are missing.

- [ ] **Step 3: Implement the server side**

`check_measurement` works in this order:
1. If `declared` is empty, return only the "declares no variables" problem.
2. If the metric is not in `declared`, or `catalog.get(metric)` is `None`, return only a problem that names the declared IDs.
3. Otherwise, collect all of these problems together:
   - the kind must be `manual`
   - the unit must match exactly (name the right unit)
   - the value must lie within `min`/`max`, inclusive

Deprecation is not checked at entry.

Wire it into `POST /measurements`, after the stage check:

```python
declared = self.workflow.store.declared_variables(body.experiment_id)
problems = check_measurement(record, self.workflow.catalog, declared)
if problems:
    raise rejected("; ".join(problems))
```

Add the GET route to `_read_routes`, and `declared_variables` to the store.

- [ ] **Step 4: Implement the form**

In `stage-measurements.js`:
- The metric field becomes `type: "select"`, with options from `variableOptions(variables, ctx.lang)`.
- `unit` is no longer a field, and it is dropped from `COPIED`.
- `onSubmit` posts `measurementBody(...)`.
- `method` stays a text field. It is filled with the chosen variable's method when the metric changes and when the form opens.
- `SUGGESTED` becomes `["method"]`.
- With no variables, render the note `ctx.t("measure.noVariables")` instead of the form.

In `stage.js`, fetch `/experiments/${stage.experiment_id}/variables` together with the measurements, and pass `variables` to the form.

Add the `measure.noVariables` text to both language files:
- en: "This experiment's protocol declares no variables. Save a protocol version that declares them before recording measurements."
- zh: "该实验的协议没有声明变量。请先保存一个声明了变量的协议版本，再录入测量。"

- [ ] **Step 5: Migrate the existing posters**

- In `workbench_support.py`:
  - `Bench` builds its `WorkflowService` with `catalog=TEST_CATALOG`.
  - `seed_round` saves `make_protocol(variables=("canopy_area_growth", "height", "yield_g"))`.
- In `tests/e2e/`, replace every `cm2/day` with `cm2/d` (`sed -i '' 's#cm2/day#cm2/d#g' tests/e2e/*.py`). Rows posted through the API and rows stored directly must share one unit.

- [ ] **Step 6: Run everything**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider && node --test tests/web/*.test.mjs`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add -A src tests
git commit -m "feat: check manual measurements against the declared variables"
```

---

### Task 6: Snapshots record the catalog they used

**Files:**
- Modify:
  - `src/growbridge/vocab/catalog.py`
  - `src/growbridge/archive/snapshot.py` (`freeze`, line 104)
  - `src/growbridge/agents/handlers_researcher.py` (`_freeze`, line 212)
- Test: `tests/archive/test_archive_snapshot.py`, `tests/vocab/test_vocab_catalog.py`

**Interfaces:**
- Consumes: `WorkflowStore.declared_variables` (Task 5), `WorkflowService.catalog` (Task 2).
- Produces:
  - `Catalog.snapshot_record(names: Iterable[str]) -> dict`, returning:
    - `"version"`
    - `"digest"`
    - `"variables"`: the full `model_dump(mode="json")` of each distinct entry the names resolve to, sorted by id
    - `"unresolved"`: the distinct names that do not resolve, sorted
  - `CATALOG_FILE = "catalog.json"` in `archive/snapshot.py`.
  - `freeze(..., declared: Collection[str] = (), catalog: Catalog | None = None)`.
- Nothing in phase 1 reads `catalog.json`. The phase 2 export must handle snapshots that lack it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/vocab/test_vocab_catalog.py`:

```python
def test_snapshot_record_resolves_and_lists_unknown_names():
    record = packaged_catalog().snapshot_record(["temp", "air_temperature", "heigth", "light"])
    assert [v["id"] for v in record["variables"]] == ["air_temperature", "light"]
    assert record["unresolved"] == ["heigth"]
    assert record["digest"] == packaged_catalog().digest
```

Add to `tests/archive/test_archive_snapshot.py`, using that file's freeze setup:
- `test_freeze_writes_catalog_json`:
  - Freeze these inputs:
    - one measurement named `canopy_area_growth`
    - one measurement named `heigth`
    - a sample with `data={"sensor": {"temp": 21.0}, "light": {"level": 40}}`
    - `declared={"canopy_area_growth"}`
  - Then check:
    - the ids in `catalog.json` are `["air_temperature", "canopy_area_growth"]`
    - `unresolved == ["heigth"]`
    - `"catalog.json" in snapshot.files`
    - `verify(archive, snapshot.id)` is true
- `test_sample_without_sensor_key_adds_no_names` (Review Focus 3): a sample with `data={}` freezes without error, and its `catalog.json` lists no sensor variable.

- [ ] **Step 2: Run the tests to see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/archive/test_archive_snapshot.py tests/vocab/test_vocab_catalog.py`
Expected: FAIL, because `snapshot_record` does not exist and no `catalog.json` is written

- [ ] **Step 3: Implement**

- `freeze` collects names from three sources:
  - `declared`
  - the `metric` of each kept measurement
  - the keys of `sample.data["sensor"]` for trusted and untrusted samples, but only when that key exists and holds a dict
- After `_write_files`, it writes `canonical_json(catalog.snapshot_record(names))` to `directory / CATALOG_FILE`.
- It adds that file's `file_digest` to the `files` map that goes into the manifest and the `Snapshot`.
- In the researcher handler, `_freeze` passes `declared=deps.workflow.store.declared_variables(experiment_id)` and `catalog=deps.workflow.catalog`.

- [ ] **Step 4: Run the tests to see them pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/archive tests/dispatch tests/research`
Expected: all pass. Frozen confirmatory scripts read only `measurements.jsonl`, so the extra file does not affect them.

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "feat: snapshots record the variable definitions they used"
```

---

### Task 7: The humidity rule also asks the catalog

**Files:**
- Modify: `src/growbridge/planning/validate.py` (`_is_humidity` 139, `_check_humidity`, `validate_run_sheet` 340)
- Test: `tests/planning/test_planning_validate.py`

**Interfaces:**
- Consumes: `Catalog.resolve`, `load_catalog`, `packaged_text` (Task 1).
- Produces:
  - `validate_run_sheet(run_sheet, capabilities, safety=None, catalog: Catalog | None = None)`
  - `_is_humidity(rule, catalog) -> bool`, which is true when `(v := catalog.resolve(rule.sensor)) is not None and v.quantity == "relative_humidity"`, or when the current substring rule matches.

- [ ] **Step 1: Write the failing tests**

Set up:
- `humidity_rule(**overrides)` from `growbridge.sim.fixtures`, with an action on a non-exhaust channel.
- `MOIST = load_catalog(packaged_text() + <entry>)`, where the entry is a sensor `leaf_air_moisture` with quantity `relative_humidity`, unit `"%"` and aliases `["moist"]`.

Tests:
- `test_catalog_humidity_name_is_exhaust_only`: a rule on sensor `"moist"`, validated with `catalog=MOIST`, produces a finding with code `humidity_exhaust_only`.
- `test_substring_rule_still_blocks_unknown_names`: a rule on sensor `"rh"` is still blocked under the packaged catalog.
- `test_catalog_never_unblocks`: a rule on `"humi"` is blocked both with and without a catalog argument.

- [ ] **Step 2: Run the tests to see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/planning/test_planning_validate.py`
Expected: FAIL, because `catalog` is an unexpected keyword

- [ ] **Step 3: Implement**

Pass `catalog or packaged_catalog()` through to `_check_humidity`. Leave `unit_mismatch` unchanged.

- [ ] **Step 4: Run the tests to see them pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/planning`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "feat: humidity rules also recognised through the variable catalog"
```

---

### Task 8: The MIAPPE export reads the real sensor keys

**Files:**
- Modify: `src/growbridge/archive/export.py` (`_variables`, line 23)
- Test: `tests/archive/test_archive_export.py`

**Interfaces:**
- Produces: `_variables` takes sensor names from `sample["data"]["sensor"]` when that is a dict, and ignores the other top-level keys. The output shape is unchanged.

- [ ] **Step 1: Write the failing test**

`test_sensor_variables_are_the_sensor_keys`: export a snapshot whose sample `data` is `{"sensor": {"temp": 21.0, "humi": 60.0}, "outlet": {}, "light": {"level": 40}, "blower": {}, "fan": {}}`. The sensor variable names must be `["humi", "temp"]`, and none of `sensor`, `outlet`, `light`, `blower` or `fan` may appear.

- [ ] **Step 2: Run the test to see it fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/archive/test_archive_export.py`
Expected: FAIL, because the names are `blower, fan, light, outlet, sensor`

- [ ] **Step 3: Implement**

Change the comprehension so it collects the keys of `data["sensor"]`.

- [ ] **Step 4: Run the test to see it pass**

Run: same as Step 2
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "fix: export the sensor readings' keys, not the sample's top-level keys"
```

---

### Task 9: Load the catalog at startup, and update the wiki

**Files:**
- Modify: `src/growbridge/runtime.py` (`build_runtime` line 627; `WorkflowService(` at 647; `HoldoutRegistry(` at 696)
- Create: `tests/vocab/test_vocab_wiring.py`
- Docs, in both `docs/wiki/en/` and `docs/wiki/zh-CN/`:
  - `Glossary.md`
  - `Run-a-Research-Round.md`
  - `Research-Methodology.md`
  - `API-Reference.md`
  - `_Sidebar.md`
  - a new `Variable-Catalog.md`

**Interfaces:**
- Consumes: every `catalog` parameter added in Tasks 2–7.
- Produces: `build_runtime` calls `packaged_catalog()` once, before building `WorkflowService`. It passes that same object to:
  - `WorkflowService`
  - `validate_run_sheet`, inside the `validate` lambda
  - `project_outcomes`
  - `HoldoutRegistry`

- [ ] **Step 1: Write the failing tests**

Build the runtime the way `tests/e2e/test_e2e_assembly.py` does.

```python
def test_runtime_shares_one_catalog(runtime):
    assert runtime.workflow.catalog is packaged_catalog()
    assert runtime.holdout.catalog is packaged_catalog()


def test_runtime_refuses_to_start_with_a_broken_catalog(monkeypatch, tmp_path):
    monkeypatch.setattr("growbridge.vocab.catalog.packaged_text", lambda: "version = [")
    packaged_catalog.cache_clear()
    try:
        with pytest.raises(CatalogError):
            build_test_runtime(tmp_path)  # the builder test_e2e_assembly.py uses
    finally:
        packaged_catalog.cache_clear()
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/vocab/test_vocab_wiring.py`
Expected: the broken-catalog test FAILS because nothing raises; the catalog is only loaded lazily

- [ ] **Step 3: Wire it**

Make the edits in `build_runtime`. `runtime.py` must stay at ≤ 800 lines.

- [ ] **Step 4: Write the wiki pages**

Write both languages, in the tone of the existing pages:
- **`Variable-Catalog.md`** (new):
  - what the catalog is for
  - the append-only rule
  - `catalog.lock.json` and the version bump
  - deprecation and `replaced_by`
  - aliases are device keys only
  - a new experiment's variables must be in the catalog before its protocol is saved
- **`Run-a-Research-Round.md`**:
  - the variable dropdown
  - what each refusal means and what to do about it
  - corrections, including that a correction invalidates the snapshots and reports that hold the original record
- **`Research-Methodology.md`**: frozen confirmatory scripts filter `measurements.jsonl` by variable ID.
- **`API-Reference.md`**:
  - `GET /wb/experiments/{experiment_id}/variables`
  - the new refusals of `POST /wb/measurements`
  - the new refusals when saving a protocol
- **`Glossary.md`**: an entry for "Variable catalog / 变量目录".
- **`_Sidebar.md`**: a link to the new page.

- [ ] **Step 5: Run the full verification**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider && node --test tests/web/*.test.mjs && .venv/bin/ruff check src tests scripts && .venv/bin/ruff format --check src tests scripts`
Expected: all pass and the lint is clean; `tests/test_runtime_size.py` passes too

- [ ] **Step 6: Commit**

```bash
git add -A src tests docs/wiki
git commit -m "feat: load the variable catalog at startup; document it"
```
