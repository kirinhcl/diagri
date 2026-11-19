# Training Dataset Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `growbridge export-dataset` command that turns one verified snapshot into a training-ready dataset directory (flat long-format CSV tables, a variables table with units and ontology terms, and `croissant.json`), plus the catalog and protocol fields it needs, replacing `export_miappe`.

**Architecture:** A new package `growbridge.dataset` builds every output file in memory from a `SnapshotData` (read from the frozen snapshot only) and an `ExportInputs` (protocol, round, current catalog, current holdouts, pseudonymizer). Pure row builders feed one table schema that drives both the CSV writer and the Croissant metadata. A thin command layer resolves the inputs from the data directory, read-only, and writes the files atomically.

**Tech Stack:** Python 3.11+ standard library only at runtime (`csv`, `hmac`, `hashlib`, `json`, `tomllib`); pydantic models already in the project; `mlcroissant` as a dev-only dependency for one read test; vanilla JS for the console form.

**Spec:** `docs/superpowers/specs/2026-11-18-training-dataset-export-design.md` (Chinese). Section numbers below (§N) refer to it. It supersedes §11 of `docs/superpowers/specs/2026-11-17-variable-catalog-design.md`.

## Global Constraints

- Runtime code uses the standard library only; no new runtime dependency (spec §3). `mlcroissant` goes into the `dev` extra only.
- The export only reads the archive, workflow and agents databases and the snapshot directory. The single file it may create inside the data directory is `<data_dir>/export/pseudonym.key` (spec §10).
- Nothing guesses an ontology term: `refs` and `[unit_refs]` stay empty until the user confirms each term (spec §5.2). No task except Task 9 writes catalog content.
- CSV format: UTF-8, LF line endings, header row first, times as UTC ISO 8601 with milliseconds and a trailing `Z`, floats via `repr`, empty field for none, rows sorted by each table's key (spec §8).
- Croissant: `conformsTo` is `http://mlcommons.org/croissant/1.1`; required dataset fields `name`, `description`, `license`, `url`, `creator`, `datePublished`, `distribution` (spec §3, §11).
- Same snapshot, catalog, holdout registry and arguments give byte-identical output; `datePublished` is the UTC date of the snapshot's `created_at` (spec §2, §11).
- Operator names and operator notes never appear in any output file (spec §8, §10).
- Every refusal carries a registered reason (`denial_codes.py`, enforced by a source-scan test). Console texts exist in en and zh.
- Protocols saved before this change keep their digest: empty `variables`, `crop_taxon` and `cultivar` are left out of the dump (spec §6). The pinned digest `43a1b3295e64a74f2e948c38755068627abd79b2bc54de64c89ab26e84cc0ce1` must keep passing.
- New modules stay under 400 lines; no file grows past 800 lines (`workflow/service.py` is already 860: add at most 4 lines there; `workflow/store.py` is already 807: add only `round_ids_of_experiment`, at most 10 lines).
- Tests: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider <paths>` and `node --test tests/web/*.test.mjs`; `.venv/bin/ruff check src tests scripts` and `.venv/bin/ruff format --check src tests scripts` must be clean before every commit.
- Commit messages: `<type>: <description>` (feat, fix, refactor, docs, test, chore); no attribution lines.
- Read files in small chunks: grep first, then 30–60 lines at a time.
- The worktree has no `.venv` yet: before Task 1 run `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'` in it, and confirm the full suite passes on the untouched branch.

## Review Focus

1. An experiment whose stages ran in two rounds or under two protocol versions: the command refuses and names what it found, instead of picking one (Task 7, `test_experiment_in_two_rounds_is_refused`).
2. Sensor values that are not numbers (`None`, strings, booleans) or not finite (`nan`, `inf`): non-numbers are not rows and are counted; non-finite floats are rows with an empty value (Task 3 `test_non_finite_floats_are_empty`, Task 4 `test_non_numeric_sensor_values_are_counted_not_exported`).
3. Free text with commas, quotes, newlines and Chinese in `plant_id`, `batch` or the protocol question: the CSV round-trips through `csv.reader` and through `mlcroissant` (Task 3 `test_text_round_trips`, golden fixture in Task 6).
4. `--out` that already exists, sits inside the data directory, or has a missing parent: refused with nothing written (Task 7).
5. A measurement whose `position` matches no unit in a multi-unit round: exported with empty `unit` and `treatment_id`, counted as unplaced (Task 5 `test_unplaced_measurement_is_kept_and_counted`).

---

### Task 1: Catalog CURIEs and unit terms

**Files:**
- Create: `src/growbridge/vocab/curie.py`
- Modify: `src/growbridge/vocab/catalog.py` (`_check_variable`, `load_catalog`, `Catalog.__init__` and `__slots__`)
- Modify: `src/growbridge/vocab/__init__.py` (export the new names)
- Test: `tests/vocab/test_vocab_refs.py`

**Interfaces:**
- Produces:
  - `PREFIXES: Mapping[str, str]`: prefix → IRI base for `PECO`, `ENVO`, `AGRO`, `PATO`, `UO`, `NCBITaxon` (OBO form `http://purl.obolibrary.org/obo/<PREFIX>_`).
  - `crop_ontology_base(prefix: str) -> str`: the base for a `CO_<digits>` prefix. Take the IRI pattern from cropontology.org's own documentation and cite the URL in a comment.
  - `curie_prefix(curie: str) -> str | None`: the prefix when `curie` matches `^(?P<prefix>[A-Za-z][A-Za-z0-9_]*):(?P<local>[A-Za-z0-9_.-]+)$` and the prefix is in `PREFIXES` or is `CO_` followed by digits; otherwise `None`.
  - `context_prefixes(curies: Iterable[str]) -> dict[str, str]`: prefix → base, for the prefixes the CURIEs use.
  - `Catalog.unit_refs: Mapping[str, str]` (read-only), from the `[unit_refs]` table.

- [ ] **Step 1: Write the failing tests** in `tests/vocab/test_vocab_refs.py`

```python
def with_first_refs(value: str) -> str:
    return packaged_text().replace("refs = []", f"refs = {value}", 1)  # air_temperature

def test_known_prefixes_load():
    cat = load_catalog(with_first_refs('["ENVO:09200001", "CO_331:0000192", "PATO:0000146"]'))
    assert cat.get("air_temperature").refs == ("ENVO:09200001", "CO_331:0000192", "PATO:0000146")

@pytest.mark.parametrize("ref", ["FOO:1", "air temperature", "ENVO:", ":123", "CO_:1", "CO_x1:1"])
def test_bad_ref_is_refused(ref):
    with pytest.raises(CatalogError, match="air_temperature"):
        load_catalog(with_first_refs(f'["{ref}"]'))

def test_unit_refs_load():
    cat = load_catalog(packaged_text() + '\n[unit_refs]\n"Cel" = "UO:0000027"\n')
    assert dict(cat.unit_refs) == {"Cel": "UO:0000027"}

def test_unit_ref_for_an_unused_unit_is_refused():
    with pytest.raises(CatalogError, match="K"):
        load_catalog(packaged_text() + '\n[unit_refs]\n"K" = "UO:0000012"\n')

def test_unit_ref_must_be_a_uo_term():
    with pytest.raises(CatalogError, match="Cel"):
        load_catalog(packaged_text() + '\n[unit_refs]\n"Cel" = "ENVO:09200001"\n')

def test_packaged_catalog_is_unchanged():
    assert packaged_catalog().version == 1
    assert dict(packaged_catalog().unit_refs) == {}

def test_context_prefixes_cover_what_is_used():
    found = context_prefixes(["ENVO:1", "CO_331:2", "ENVO:3"])
    assert set(found) == {"ENVO", "CO_331"}
    assert found["ENVO"] == "http://purl.obolibrary.org/obo/ENVO_"
    assert found["CO_331"].startswith("http") and "CO_331" in found["CO_331"]
```

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/vocab/test_vocab_refs.py`
Expected: FAIL (import error for `context_prefixes`, no `unit_refs`)

- [ ] **Step 3: Implement `curie.py` and wire it into the loader.** `_check_variable` reports `f"{name}: ref {ref} is not a CURIE with a known prefix"`. `load_catalog` validates `[unit_refs]`: it must map text to text; every key must be the `unit` of some entry (`f"unit_refs: {key} is not a unit any entry uses"`); every value must have prefix `UO` (`f"unit_refs: {key} must map to a UO term"`). Pass the mapping to `Catalog(..., unit_refs=...)`, a keyword parameter that defaults to empty and is stored as a `MappingProxyType`. The catalog digest stays the sha256 of the text, so the lock test is untouched.

- [ ] **Step 4: Run the vocab tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/vocab`
Expected: PASS (including the existing lock test)

- [ ] **Step 5: Commit**

```bash
git add src/growbridge/vocab tests/vocab/test_vocab_refs.py
git commit -m "feat: check catalog refs as known CURIEs and add unit_refs"
```

---

### Task 2: Protocol crop species and cultivar

**Files:**
- Modify: `src/growbridge/archive/models.py` (`ResearchProtocol` fields and serializer)
- Modify: `src/growbridge/vocab/curie.py` (add `taxon_problems`)
- Modify: `src/growbridge/workflow/service.py:115-135` (`save_protocol`)
- Modify: `src/growbridge/workflow/denials.py`, `src/growbridge/denial_codes.py`
- Modify: `src/growbridge/web/workbench/i18n/denials.en.js`, `denials.zh.js`, `forms.en.js`, `forms.zh.js`
- Modify: `src/growbridge/web/workbench/pages/protocol-form.js` (`basicFields`, `buildProtocol`, the empty skeleton)
- Modify: `src/growbridge/sim/fixtures.py` (`make_protocol` default)
- Modify: `tests/web/fixtures/message-codes.json` (regenerate with `scripts/export_message_codes.py`, run as its docstring says)
- Test: `tests/vocab/test_vocab_protocol.py`, `tests/vocab/test_vocab_taxon.py`, the workflow test file that already covers `protocol_variables_invalid`, `tests/web/protocol-form.test.mjs`

**Interfaces:**
- Consumes: `curie.py` from Task 1.
- Produces:
  - `ResearchProtocol.crop_taxon: str = ""` and `ResearchProtocol.cultivar: str = ""`.
  - `taxon_problems(crop_taxon: str, cultivar: str) -> list[str]` in `growbridge.vocab.curie`.
  - `denials.protocol_crop_taxon_invalid(protocol_id: str, version: int, problems: list[str]) -> Denied`, which returns `Denied("param", "; ".join(problems), reason="protocol_crop_taxon_invalid", params={"protocol_id": protocol_id, "version": version})`.

- [ ] **Step 1: Write the failing tests**

In `tests/vocab/test_vocab_taxon.py`:

```python
@pytest.mark.parametrize("taxon", ["NCBITaxon:4236", "NCBITaxon:9"])
def test_valid_taxon_has_no_problems(taxon):
    assert taxon_problems(taxon, "") == []

@pytest.mark.parametrize("taxon", ["", "NCBITaxon:abc", "ncbitaxon:4236", "NCBITaxon:4236 ", "4236"])
def test_bad_taxon_is_a_problem(taxon):
    problems = taxon_problems(taxon, "")
    assert len(problems) == 1 and "crop_taxon" in problems[0]

def test_cultivar_up_to_200_characters():
    assert taxon_problems("NCBITaxon:4236", "x" * 200) == []
    assert any("200" in p for p in taxon_problems("NCBITaxon:4236", "x" * 201))
```

In `tests/vocab/test_vocab_protocol.py`, change the pinned test to `make_protocol(variables=(), crop_taxon="").digest() == PRE_CHANGE_DIGEST` and add:

```python
def test_protocol_without_crop_fields_dumps_as_before():
    raw = make_protocol(variables=(), crop_taxon="", cultivar="").model_dump(mode="json")
    assert "crop_taxon" not in raw and "cultivar" not in raw

def test_crop_fields_are_dumped_when_set():
    raw = make_protocol(crop_taxon="NCBITaxon:4236", cultivar="Grand Rapids").model_dump(mode="json")
    assert raw["crop_taxon"] == "NCBITaxon:4236" and raw["cultivar"] == "Grand Rapids"
```

Next to the existing `protocol_variables_invalid` workflow test, add `test_save_protocol_refuses_a_protocol_without_crop_taxon`. Save `make_protocol(crop_taxon="")` as a designer and expect `Denied` with `reason == "protocol_crop_taxon_invalid"` and `params == {"protocol_id": <id>, "version": <version>}`.

In `tests/web/protocol-form.test.mjs`, assert:
- the form renders `crop_taxon` (required) and `cultivar` fields;
- `buildProtocol` puts both values into the protocol;
- the skeleton has `crop_taxon: ""` and `cultivar: ""`.

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/vocab tests/workflow` and `node --test tests/web/protocol-form.test.mjs`
Expected: FAIL

- [ ] **Step 3: Implement**

`taxon_problems` checks:
- `crop_taxon` against `^NCBITaxon:[0-9]+$`. When empty, the problem reads `"name the crop species as an NCBI Taxonomy ID: crop_taxon = NCBITaxon:<number>"`; otherwise `f"crop_taxon {value} is not NCBITaxon:<number>"`.
- `cultivar` is at most 200 characters (`"cultivar is longer than 200 characters"`).

The serializer drops each of `variables`, `crop_taxon` and `cultivar` when empty.

`save_protocol` runs `taxon_problems` right after the variables check, for new versions only, and raises `protocol_crop_taxon_invalid` when any problem is found.

Register `("protocol_crop_taxon_invalid", ("protocol_id", "version"))` under `param` in `denial_codes.py`.

Console texts:
- en `msg.denial.protocol_crop_taxon_invalid`: "Version {version} of this protocol does not name its crop species correctly."
- en `.action`: "Give the crop species as an NCBI Taxonomy ID in the form NCBITaxon:<number> (look it up at NCBI Taxonomy) and keep the cultivar under 200 characters; the technical details list every problem."
- zh `msg.denial.protocol_crop_taxon_invalid`: "方案的版本 {version} 没有正确写明作物物种。"
- zh `.action`: "请用 NCBI Taxonomy 的编号写作物物种，格式为 NCBITaxon:<数字>（到 NCBI Taxonomy 查询），品种名不超过 200 个字符；每个问题都列在技术详情里。"

Form changes:
- Insert the two fields right after `crop`:
  - `crop_taxon`, required, with hint keys `protocol.form.cropTaxon` and `protocol.form.cropTaxonHint`;
  - `cultivar`, optional, with key `protocol.form.cultivar`.
- The hint gives the format and says to look it up at NCBI Taxonomy. It names no example species ID.
- en/zh texts:
  - en: "Crop species (NCBI Taxonomy)" / "Write it as NCBITaxon:<number>; find the number at NCBI Taxonomy." / "Cultivar"
  - zh: "作物物种（NCBI Taxonomy）" / "格式为 NCBITaxon:<数字>，编号到 NCBI Taxonomy 查询。" / "品种"
- Update the "server asks nothing of the crop" comment, since it is no longer true for the species.

`make_protocol` default `crop_taxon`:
- the NCBI Taxonomy ID of *Lactuca sativa* (the fixture crop is lettuce);
- look it up at https://www.ncbi.nlm.nih.gov/taxonomy and write it as `NCBITaxon:<id>`;
- the expected ID is 4236; if the lookup disagrees, use the lookup and say so in the report.

Fix any other test that saves a protocol built without `make_protocol`: give it a `crop_taxon`, never weaken the check. The same goes for any code under `src/` or `scripts/` that saves a protocol (simulation, demo or dev-workbench seeding).

- [ ] **Step 4: Regenerate the message-code fixture and run everything touched**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider` and `node --test tests/web/*.test.mjs`
Expected: PASS (full suites: the source-scan denial test and i18n parity tests included)

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "feat: protocols name the crop species and cultivar"
```

---

### Task 3: Dataset schema, CSV format, pseudonyms and triggers

**Files:**
- Create: `src/growbridge/dataset/__init__.py`, `schema.py`, `csvfmt.py`, `pseudonym.py`, `triggers.py`
- Test: `tests/dataset/test_dataset_schema.py`, `test_dataset_csvfmt.py`, `test_dataset_pseudonym.py`, `test_dataset_triggers.py`

**Interfaces:**
- Produces:
  - `DataType = Literal["Text", "Float", "Integer", "Boolean", "DateTime"]`.
  - `@dataclass(frozen=True) class Column: name: str; data_type: DataType; description: str; references: str | None = None`. `references` takes the form `"<file>.<column>"`, e.g. `"variables.csv.variable_id"`.
  - `@dataclass(frozen=True) class Table: file: str; description: str; columns: tuple[Column, ...]; sort_key: tuple[str, ...]`.
  - `TABLES: tuple[Table, ...]` and `table(file: str) -> Table`.
  - `format_time(seconds: float) -> str`, `format_cell(value: object, data_type: DataType) -> str`, `write_csv(table: Table, rows: Iterable[Mapping[str, object]]) -> bytes`.
  - `load_or_create_key(path: Path) -> bytes`, `class Pseudonymizer: __init__(self, key: bytes); __call__(self, name: str | None) -> str | None`.
  - `class CleanedTrigger(NamedTuple): value: str; note_dropped: bool; other: bool`, `clean_trigger(trigger: str) -> CleanedTrigger`.

`TABLES`, in this order, with exactly these columns (spec §8; data types are the builder's reading of each column):

| file | columns | sort_key |
|---|---|---|
| `variables.csv` | variable_id, kind, label_en, quantity, unit_ucum, unit_uo, method, min, max, refs, mapped | variable_id |
| `treatments.csv` | treatment_id, name, is_control, variable_id, value | treatment_id, variable_id |
| `units.csv` | round, block, unit, treatment_id | round, unit |
| `sensor_readings.csv` | time, time_source, clock_synced, sample_id, device_id, experiment_id, stage_id, round, variable_id, raw_key, value, quality, stuck | time, sample_id, raw_key |
| `sensor_readings_untrusted.csv` | same as `sensor_readings.csv` | same |
| `device_states.csv` | time, time_source, clock_synced, sample_id, device_id, experiment_id, stage_id, round, key, value, quality | time, sample_id, key |
| `device_states_untrusted.csv` | same as `device_states.csv` | same |
| `measurements.csv` | time, record_id, corrects, experiment_id, round, batch, unit, treatment_id, plant_id, position, layout_version, variable_id, value, method, operator | time, record_id |
| `actions.csv` | request_id, channel, state, trigger, planned_level, confirmed_level, created_at, sent_at, confirmed_at, ran_seconds, error_code, ended_early_code, supersedes, operator | created_at, request_id |
| `interventions.csv` | id, time, stage_id, kind, detail, operator | time, id |
| `withheld.csv` | holdout_id, batch, variable_id | holdout_id, batch, variable_id |

`references`:
- every `variable_id` column except `variables.csv` and `withheld.csv` references `variables.csv.variable_id`;
- `treatment_id` in `units.csv` and `measurements.csv` references `treatments.csv.treatment_id`.
- `withheld.csv.variable_id` can be `*`, so it has no reference.

`treatments.csv.value` is `Text`: a treatment factor's value may be a string. Numbers in it are written with `repr`.

Trigger allowlist (taken from every `trigger=` writer in `src/growbridge`: `workbench/api.py`, `workbench/manual_tasks.py`, `executor/engine.py` with `WriteKind`, `ports.PumpOffTrigger`):

| input | value | note_dropped | other |
|---|---|---|---|
| `manual` | `manual` | False | False |
| `manual: <anything>` | `manual` | True | False |
| `planned irrigation <id>` | same | False | False |
| `planned irrigation <id>: <anything>` | `planned irrigation <id>` | True | False |
| `<kind>:<id>` with kind in `rule`, `protect`, `end`, `experiment_action`, `care`, `protection` | same | False | False |
| `interlock`, `watchdog` | same | False | False |
| anything else | `other` | False | True |

`<id>` matches `[A-Za-z0-9_.-]+`.

The `key` column's description in both device-state tables lists every key the controller reports (`light.level`, `light.on`, `fan.level`, `fan.on`, `blower.level`, `blower.on`, `outlet.O1.on` … `outlet.O5.on`). Each gets its meaning and range, taken from the code that parses device readings (grep for where `"blower"` / `"outlet"` are read). Where the code does not say what a level means, write "as reported by the controller; scale not documented" rather than guess.

- [ ] **Step 1: Write the failing tests**

```python
def test_tables_match_the_spec():
    assert [t.file for t in TABLES] == ["variables.csv", "treatments.csv", "units.csv",
        "sensor_readings.csv", "sensor_readings_untrusted.csv", "device_states.csv",
        "device_states_untrusted.csv", "measurements.csv", "actions.csv",
        "interventions.csv", "withheld.csv"]
    assert [c.name for c in table("withheld.csv").columns] == ["holdout_id", "batch", "variable_id"]
    for t in TABLES:
        assert set(t.sort_key) <= {c.name for c in t.columns}
        # one assertion per table pins the column names of the table above

def test_format_time():
    assert format_time(0.0) == "1970-01-01T00:00:00.000Z"
    assert format_time(1700000000.1234) == "2023-11-14T22:13:20.123Z"

def test_format_cell():
    assert format_cell(None, "Float") == ""
    assert format_cell(0.1, "Float") == "0.1" and format_cell(3, "Float") == "3.0"
    assert format_cell(True, "Boolean") == "true" and format_cell(7, "Integer") == "7"

@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_floats_are_empty(value):
    assert format_cell(value, "Float") == ""

def test_text_round_trips():
    t = Table("x.csv", "", (Column("a", "Text", ""), Column("b", "Float", "")), ("a",))
    text = 'A,"1"\n二'
    data = write_csv(t, [{"a": text, "b": 1.5}])
    assert b"\r" not in data and data.endswith(b"\n")
    assert list(csv.reader(io.StringIO(data.decode("utf-8")))) == [["a", "b"], [text, "1.5"]]

def test_rows_sorted_with_none_first():
    t = Table("x.csv", "", (Column("a", "Text", ""),), ("a",))
    # Python's csv writes a row whose only field is empty as "" (an empty line would read as no row)
    assert write_csv(t, [{"a": "b"}, {"a": None}, {"a": "a"}]) == b'a\n""\na\nb\n'

def test_unknown_column_is_an_error():
    t = Table("x.csv", "", (Column("a", "Text", ""),), ("a",))
    with pytest.raises(ValueError):
        write_csv(t, [{"a": "x", "zz": 1}])

def test_pseudonyms(tmp_path):
    key = load_or_create_key(tmp_path / "export" / "pseudonym.key")
    assert len(key) == 32 and load_or_create_key(tmp_path / "export" / "pseudonym.key") == key
    assert stat.S_IMODE((tmp_path / "export" / "pseudonym.key").stat().st_mode) == 0o600
    p = Pseudonymizer(key)
    assert re.fullmatch(r"op-[0-9a-f]{12}", p("alice"))
    assert p("alice") == p("alice") != p("bob") and p(None) is None

def test_key_of_wrong_length_is_refused(tmp_path):
    (tmp_path / "k").write_bytes(b"short")
    with pytest.raises(ValueError):
        load_or_create_key(tmp_path / "k")
```

`test_dataset_triggers.py` is one parametrized test over the allowlist table above, plus these inputs, which must give `other`: `"rule: free text"`, `"manualish"`, `"planned irrigation"`, `"rule:"`.

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/dataset`
Expected: FAIL (no module `growbridge.dataset`)

- [ ] **Step 3: Implement the four modules**

- `write_csv` uses `csv.writer(..., lineterminator="\n")` with minimal quoting.
- It sorts by `sort_key`, using `(value is not None, value)` per key.
- It formats every cell with `format_cell` and the column's type.
- `format_time` uses `datetime.fromtimestamp(s, UTC).isoformat(timespec="milliseconds")` with `+00:00` replaced by `Z`.
- `load_or_create_key` creates the parent directory with mode 0o700 and the file with `os.open(..., O_CREAT | O_EXCL | O_WRONLY, 0o600)` and 32 bytes from `secrets.token_bytes`.

- [ ] **Step 4: Run them**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/dataset`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/growbridge/dataset tests/dataset
git commit -m "feat: dataset table schema, CSV format, pseudonyms and trigger cleaning"
```

---

### Task 4: Snapshot reading and sample rows

**Files:**
- Create: `src/growbridge/dataset/source.py`, `src/growbridge/dataset/rows_samples.py`
- Test: `tests/dataset/test_dataset_source.py`, `tests/dataset/test_dataset_rows_samples.py`

**Interfaces:**
- Consumes: `snapshot.verify`, `snapshot.load`, `CATALOG_FILE`, `MANIFEST` from `growbridge.archive.snapshot`; the models `SampleRecord`, `ManualMeasurement`, `ActionRecord`, `FrozenPeriod`, `Snapshot`.
- Produces:
  - `class ExportRefused(Exception)`. Its message is shown to the person as is.
  - `@dataclass(frozen=True) class SnapshotData` with these fields:
    - `snapshot: Snapshot`
    - `manifest: Mapping[str, Any]`
    - `catalog_record: Mapping[str, Any]`
    - `samples: tuple[SampleRecord, ...]`
    - `samples_untrusted: tuple[SampleRecord, ...]`
    - `measurements: tuple[ManualMeasurement, ...]`
    - `actions: tuple[ActionRecord, ...]`
    - `interventions: tuple[Mapping[str, Any], ...]`
    - `frozen_periods: tuple[Mapping[str, Any], ...]`: the rows of `frozen_periods.jsonl` as frozen. They are the dicts `Archive.frozen_periods` returns (`period_id`, `sensor`, `value`, `first_at`, `last_at`, `opened_at`, `closed_at`, `close_reason`; `last_at` is None while the period is open), not `FrozenPeriod` models.
  - `read_snapshot(archive: Archive, snapshot_id: str) -> SnapshotData`.
  - `time_of(sample: SampleRecord) -> tuple[float, str]`: returns `(captured_at, "captured")` when `captured_at` is set and `clock_synced` is true, else `(received_at, "received")`.
  - `@dataclass(frozen=True) class SampleRows: sensor: tuple[dict, ...]; device: tuple[dict, ...]; unresolved_keys: int; non_numeric: int`.
  - `sample_rows(samples: Sequence[SampleRecord], round_number: int, catalog: Catalog, frozen: Sequence[Mapping[str, Any]]) -> SampleRows`. Row dicts use the column names of `sensor_readings.csv` / `device_states.csv` (Task 3), with raw Python values.

Rules (spec §8):
- **Sensor rows.** One row per key of `data["sensor"]`. `variable_id` is `catalog.canonical(key)` (None when unresolved, counted in `unresolved_keys`). `raw_key` is the key.
- **Device rows.** One row per numeric leaf of `data` outside `sensor`, keyed the way `snapshot._numbers` joins them (`light.level`, `outlet.O1.on`).
- **Non-numeric values.** A value that is not an `int`/`float`, or is a `bool`, is not a row and counts in `non_numeric`, for both kinds.
- **`stuck`.** True when a frozen period's `sensor` names the same variable as the reading's key (`catalog.same`; both are device keys such as `temp`) and the reading's time `t` satisfies `first_at <= t` and (`last_at` is None or `t <= last_at`). `last_at` is the last time the sensor still reported the frozen value (`observer/frozen_watch.py`, `_close`).

- [ ] **Step 1: Write the failing tests**

`test_dataset_source.py`:
- `test_reads_a_frozen_snapshot`: freeze with the `archive` and `clock` fixtures as `tests/archive/test_archive_export.py` does; `read_snapshot` returns the samples and measurements, and `catalog_record["version"] == 1`.
- `test_unknown_snapshot_is_refused`: `pytest.raises(ExportRefused, match="snap-missing")`.
- `test_tampered_snapshot_is_refused`: append a byte to `samples.jsonl`, then expect `ExportRefused` mentioning verification.
- `test_snapshot_without_catalog_is_refused`: monkeypatch `archive.snapshot` to return a copy whose `files` lacks `catalog.json`, and `verify` to return True. Expect `ExportRefused` mentioning `catalog.json`.

`test_dataset_rows_samples.py`:

```python
def test_time_source():
    assert time_of(sample(captured_at=10.0, received_at=11.0, clock_synced=True)) == (10.0, "captured")
    assert time_of(sample(captured_at=10.0, received_at=11.0, clock_synced=False)) == (11.0, "received")
    assert time_of(sample(captured_at=None, received_at=11.0, clock_synced=True)) == (11.0, "received")

def test_sensor_keys_resolve_through_aliases():
    rows = sample_rows([sample(data={"sensor": {"temp": 24.0, "leafwet": 1.0}})], 2, packaged_catalog(), [])
    by_key = {r["raw_key"]: r for r in rows.sensor}
    assert by_key["temp"]["variable_id"] == "air_temperature" and by_key["temp"]["round"] == 2
    assert by_key["leafwet"]["variable_id"] is None and rows.unresolved_keys == 1

def test_non_numeric_sensor_values_are_counted_not_exported():
    rows = sample_rows([sample(data={"sensor": {"temp": "n/a", "humi": None, "co2": True, "vpd": float("nan")}})], 1, packaged_catalog(), [])
    assert [r["raw_key"] for r in rows.sensor] == ["vpd"] and rows.non_numeric == 3

def test_device_states():
    data = {"sensor": {"temp": 20.0}, "light": {"level": 70, "on": 1}, "outlet": {"O1": {"on": 0}}, "mode": "auto"}
    rows = sample_rows([sample(data=data)], 1, packaged_catalog(), [])
    assert sorted(r["key"] for r in rows.device) == ["light.level", "light.on", "outlet.O1.on"]
    assert rows.non_numeric == 1

def test_stuck_readings():
    period = {"period_id": "f1", "sensor": "temp", "value": 20.0, "first_at": 100.0, "last_at": None,
              "opened_at": 160.0, "closed_at": None, "close_reason": None}
    s = [sample(id="a", captured_at=90.0, data={"sensor": {"temp": 20.0, "humi": 50.0}}),
         sample(id="b", captured_at=110.0, data={"sensor": {"temp": 20.0, "humi": 50.0}})]
    rows = sample_rows(s, 1, packaged_catalog(), [period])
    stuck = {(r["sample_id"], r["raw_key"]): r["stuck"] for r in rows.sensor}
    assert stuck == {("a", "temp"): False, ("a", "humi"): False, ("b", "temp"): True, ("b", "humi"): False}

def test_a_closed_period_ends_at_last_at():
    period = {"period_id": "f1", "sensor": "air_temperature", "value": 20.0, "first_at": 100.0,
              "last_at": 120.0, "opened_at": 160.0, "closed_at": 200.0, "close_reason": "value_changed"}
    s = [sample(id=i, captured_at=t, data={"sensor": {"temp": 20.0}}) for i, t in (("a", 120.0), ("b", 130.0))]
    rows = sample_rows(s, 1, packaged_catalog(), [period])
    assert {r["sample_id"]: r["stuck"] for r in rows.sensor} == {"a": True, "b": False}
```

`sample(...)` is a small local helper that builds a `SampleRecord` with defaults.

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/dataset`
Expected: FAIL

- [ ] **Step 3: Implement `source.py` and `rows_samples.py`.** `read_snapshot` validates each JSONL line with the matching model, and `interventions.jsonl` lines as plain dicts. Look up `snapshot.load` first and turn `KeyError` into `ExportRefused`. Then call `verify`, then check that `CATALOG_FILE` is in `snapshot.files`.

- [ ] **Step 4: Run them**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/dataset`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/growbridge/dataset tests/dataset
git commit -m "feat: read verified snapshots and build sensor and device-state rows"
```

---

### Task 5: Measurement, action, design and withheld rows

**Files:**
- Modify: `src/growbridge/planning/treatment.py` (add `unit_of`)
- Modify: `src/growbridge/agents/handlers_report.py` (`_missing_fraction` uses `unit_of`; behaviour unchanged)
- Create: `src/growbridge/dataset/rows_records.py`, `src/growbridge/dataset/rows_design.py`
- Test: `tests/planning/test_planning_unit_of.py`, `tests/dataset/test_dataset_rows_records.py`, `tests/dataset/test_dataset_rows_design.py`

**Interfaces:**
- Consumes: `ExportRefused`, `Pseudonymizer`, `clean_trigger` (Tasks 3–4); `Holdout` from `growbridge.research.holdout`; `canonical_json` from `growbridge.archive.ids`.
- Produces:
  - `unit_of(protocol: ResearchProtocol, round_number: int, position: str) -> Allocation | None`. With one allocation in the round, that allocation; otherwise the allocation whose `unit == position`; otherwise None. This is the rule `_missing_fraction` applies today.
  - `@dataclass(frozen=True) class MeasurementRows: rows: tuple[dict, ...]; superseded: int; withheld_at_export: int; unplaced: int`.
  - `measurement_rows(measurements: Sequence[ManualMeasurement], keep: Callable[[ManualMeasurement], bool], protocol: ResearchProtocol, round_number: int, catalog: Catalog, pseudonym: Pseudonymizer) -> MeasurementRows`.
  - `withheld_rows(holdouts: Sequence[Holdout], catalog: Catalog) -> tuple[dict, ...]`.
  - `@dataclass(frozen=True) class ActionRows: rows: tuple[dict, ...]; notes_dropped: int; other_triggers: int`, `action_rows(actions: Sequence[ActionRecord], pseudonym: Pseudonymizer) -> ActionRows`.
  - `intervention_rows(interventions: Sequence[Mapping[str, Any]], pseudonym: Pseudonymizer) -> tuple[dict, ...]`.
  - `variable_rows(referenced: Iterable[str], catalog_record: Mapping[str, Any], current: Catalog) -> tuple[dict, ...]`.
  - `treatment_rows(protocol: ResearchProtocol) -> tuple[dict, ...]`, `unit_rows(protocol: ResearchProtocol) -> tuple[dict, ...]`.

Rules (spec §8, §9):
- **`measurement_rows`.**
  - A record is superseded when another record in the input has `corrects` equal to its `id`. Superseded records are not rows; they are counted.
  - A record the `keep` filter rejects is not a row (`withheld_at_export`).
  - `variable_id` is `catalog.canonical(metric)`.
  - A record whose `unit`, mapped through `catalog.unit_aliases`, differs from the variable's unit raises `ExportRefused` naming the record id.
  - A record whose `metric` the catalog cannot resolve also raises `ExportRefused` naming the record id. `measurements.csv` has no column for a raw name, and blanking it would drop information silently. Entry checks since the variable catalog make this unreachable for new data.
  - `unit` and `treatment_id` come from `unit_of`; when there is none, both are None and the record counts as `unplaced`.
- **`withheld_rows`.** One row per (holdout, batch, outcome field resolved by `catalog.canonical`), returned sorted by `(holdout_id, batch, variable_id)`. A holdout with any unresolvable outcome field gives one row per batch with `variable_id == "*"`, and no per-field rows.
- **`variable_rows`.**
  - Defining fields come from the entry in `catalog_record["variables"]` when present, else from `current` (they cannot differ).
  - `refs` (space-joined) and `unit_uo` (from `current.unit_refs`) always come from `current`.
  - `mapped` is `bool(refs)`.
  - An id found in neither raises `ExportRefused`.
- **`treatment_rows`.** One row per (treatment, factor key), with `is_control = treatment.id == protocol.control_treatment_id`. A treatment with no factors gives one row with `variable_id` and `value` None.
- **`unit_rows`.** One row per allocation of the protocol (all rounds).

- [ ] **Step 1: Write the failing tests**

`tests/planning/test_planning_unit_of.py`:
- one allocation in the round, any position → that allocation;
- two allocations → the one whose unit equals the position;
- no match → None.

`tests/dataset/test_dataset_rows_records.py`:

```python
def test_only_the_last_correction_is_a_row():
    rows = measurement_rows([m("m1"), m("m2", corrects="m1"), m("m3", corrects="m2")], KEEP_ALL, PROTOCOL, 1, CAT, P)
    assert [(r["record_id"], r["corrects"]) for r in rows.rows] == [("m3", "m2")] and rows.superseded == 2

def test_rows_the_filter_rejects_are_withheld():
    rows = measurement_rows([m("m1"), m("m2")], lambda x: x.id != "m2", PROTOCOL, 1, CAT, P)
    assert [r["record_id"] for r in rows.rows] == ["m1"] and rows.withheld_at_export == 1

def test_operator_is_a_pseudonym():
    (row,) = measurement_rows([m("m1", operator="alice")], KEEP_ALL, PROTOCOL, 1, CAT, P).rows
    assert row["operator"] == P("alice") and "alice" not in map(str, row.values())

def test_unit_mismatch_is_refused():
    with pytest.raises(ExportRefused, match="m1"):
        measurement_rows([m("m1", unit="mm2/d")], KEEP_ALL, PROTOCOL, 1, CAT, P)

def test_unplaced_measurement_is_kept_and_counted():
    rows = measurement_rows([m("m1", position="nowhere")], KEEP_ALL, TWO_UNIT_PROTOCOL, 1, CAT, P)
    assert rows.rows[0]["unit"] is None and rows.rows[0]["treatment_id"] is None and rows.unplaced == 1

def test_withheld_rows():
    rows = withheld_rows([holdout("h1", ("b2", "b1"), ("canopy_area_growth",)), holdout("h2", ("b3",), ("not_in_catalog", "canopy_area_growth"))], CAT)
    assert [(r["holdout_id"], r["batch"], r["variable_id"]) for r in rows] == [
        ("h1", "b1", "canopy_area_growth"), ("h1", "b2", "canopy_area_growth"), ("h2", "b3", "*")]

def test_triggers_lose_their_notes():
    rows = action_rows([action("a1", trigger="manual: Alice moved the lamp"), action("a2", trigger="weird")], P)
    assert [r["trigger"] for r in rows.rows] == ["manual", "other"]
    assert rows.notes_dropped == 1 and rows.other_triggers == 1

def test_intervention_detail_is_canonical_json():
    (row,) = intervention_rows([{"id": "i1", "experiment_id": "e", "stage_id": "s", "kind": "takeover", "detail": {"b": 1, "a": 2}, "operator": "bob", "at": 5.0}], P)
    assert row["detail"] == canonical_json({"b": 1, "a": 2})
    assert row["operator"] == P("bob") and row["time"] == 5.0
```

`tests/dataset/test_dataset_rows_design.py`:
- `variable_rows(["air_temperature"], record, CAT_WITH_REFS)`: defining fields come from the record, `refs` and `unit_uo` from the current catalog, and `mapped` is True only when refs are present. Build `CAT_WITH_REFS` the way Task 1's tests do.
- An unknown id raises `ExportRefused`.
- `treatment_rows` covers the control flag and a treatment without factors.
- `unit_rows` returns every allocation.

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/dataset tests/planning`
Expected: FAIL

- [ ] **Step 3: Implement.** Refactor `_missing_fraction` to use `unit_of`: a planned `(round, unit)` is present when some position measured in that round maps to it. Then add the row builders.

- [ ] **Step 4: Run them, plus the report tests as a regression guard**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/dataset tests/planning tests/agents`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/growbridge tests
git commit -m "feat: measurement, action, design and withheld rows for the dataset export"
```

---

### Task 6: Croissant metadata, the dataset build and golden files

**Files:**
- Create: `src/growbridge/dataset/croissant.py`, `src/growbridge/dataset/build.py`
- Create: `tests/dataset_support.py` (fixture builder, importable as `from dataset_support import ...`)
- Create: `tests/dataset/golden/` (the 12 expected files)
- Modify: `pyproject.toml` (`dev` extra: `mlcroissant`, pinned to a release at least two weeks old that supports Croissant 1.1; check with `pip index versions mlcroissant`)
- Test: `tests/dataset/test_dataset_build.py`, `tests/dataset/test_dataset_croissant_reads.py`

**Interfaces:**
- Consumes: everything from Tasks 1 and 3–5.
- Produces:
  - `@dataclass(frozen=True) class ExportInputs` with these fields:
    - `data: SnapshotData`
    - `protocol: ResearchProtocol`
    - `round_number: int`
    - `catalog: Catalog`
    - `holdouts: tuple[Holdout, ...]`
    - `keep: Callable[[ManualMeasurement], bool]`
    - `pseudonym: Pseudonymizer`
    - `licence: str`
    - `creator: str`
    - `url: str | None`
    - `corrected_after_freeze: tuple[str, ...]`
    - `software_version: str`
  - `COUNT_NAMES: tuple[str, ...]`:
    - `"unmapped_variables"`
    - `"unresolved_sensor_keys"`
    - `"non_numeric_values"`
    - `"excluded_at_freeze"`
    - `"withheld_at_export"`
    - `"superseded_records"`
    - `"corrected_after_freeze"`
    - `"notes_dropped"`
    - `"other_triggers"`
    - `"unplaced_measurements"`
  - `build_dataset(inputs: ExportInputs) -> dict[str, bytes]`: file name → content. Holds the 11 CSV files and `croissant.json`. Refuses (`ExportRefused`) an empty `protocol.crop_taxon`, and a blank `licence` or `creator`.
  - `croissant(tables: Mapping[str, bytes], inputs: ExportInputs, counts: Mapping[str, int]) -> dict`.

Croissant content (spec §11):
- `@context`: the standard Croissant 1.1 context, plus `prov`, plus `context_prefixes` of every CURIE used (variable refs, `unit_uo`, `crop_taxon`).
- `name`: `diagri-<snapshot id>`.
- `description`: the protocol question and hypothesis.
- `license`, `creator`: from the inputs.
- `url`: `inputs.url` or `urn:diagri:snapshot:<snapshot id>`.
- `datePublished`: the UTC date of `snapshot.created_at`.
- `version`: `str(snapshot.version)`.
- `about`: `{"@id": crop_taxon}`.
- One `cr:FileObject` per CSV, with `contentUrl` (the file name), `encodingFormat` `text/csv` and `sha256`.
- One `cr:RecordSet` per `Table`, with each `cr:Field` carrying `dataType` (`sc:<Type>`, where `DateTime` is `sc:DateTime`) and `source.extract.column`. When the column has `references`, the field gets a `references` entry pointing at the referenced field.
- `prov:wasDerivedFrom`: the snapshot id and its `manifest_sha256`.
- `prov:wasGeneratedBy`: `growbridge` plus `software_version` plus `export-dataset`.
- `additionalProperty` (`sc:PropertyValue` with `name`/`value`):
  - `cultivar`;
  - facility type, as text `controlled-environment grow tent` with no `propertyID` until a confirmed term exists;
  - the snapshot catalog version and the current catalog version;
  - `coverage`, and `gaps` as JSON text;
  - every `COUNT_NAMES` entry;
  - `corrected_after_freeze` as a space-joined list.
- Written as `json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"`, UTF-8.

`excluded_at_freeze` is `data.manifest["measurements_excluded"]`.

`variable_rows` receives every variable id the dataset mentions, so every `references` link resolves: `protocol.variables`, every non-empty `variable_id` in the sensor, measurement and treatment rows, and every `withheld.csv` id other than `*`.

The golden fixture (`dataset_support.build_fixture(archive, clock) -> ExportInputs`) contains (spec §13):
- two rounds, where the protocol's round 1 has two units;
- the snapshot is of round 1;
- a correction chain;
- a frozen period;
- one sample without `captured_at`;
- an unresolvable sensor key;
- samples with light, fan and outlet states, plus one non-numeric device leaf;
- one manual action and one planned-irrigation action, each with a note that contains the operator's name and the phrase `secret-note-text`;
- a holdout registered **before** the freeze (its rows are excluded at freeze) and one registered **after** it (its rows are withheld at export);
- a `plant_id` of `'A,"1"\n二'`;
- a protocol question with a comma and Chinese text.

Build it through the real archive, `snap.freeze` and `HoldoutRegistry` APIs, not by writing files. Use `software_version="0.0.0-test"`.

The golden files must not depend on the run:
- `new_id` (`archive/ids.py`) is `uuid4`, so snapshot ids and other generated ids change on every run. `build_fixture` takes pytest's `monkeypatch` and replaces `new_id` with a deterministic counter in every module that imported it and that the fixture reaches (at least `growbridge.archive.snapshot` and `growbridge.archive.store`).
- The pseudonymizer uses a fixed key (`bytes(range(32))`).
- The clock is the sim clock from the `clock` fixture.
- `test_golden` must pass in two separate `pytest` processes run one after the other.

`dataset_support` also exports the names the tests below use:
- `GOLDEN`: the path of `tests/dataset/golden`;
- `OPERATOR_NAMES`: every operator name in the fixture;
- `HELD_RECORD_IDS`: the ids of the measurements either holdout hides;
- `read_rows(data: bytes) -> list[dict[str, str]]`: a `csv.DictReader` over the bytes.

- [ ] **Step 1: Write the failing tests**

```python
def test_golden(archive, clock):
    files = build_dataset(build_fixture(archive, clock))
    assert sorted(files) == sorted([t.file for t in TABLES] + ["croissant.json"])
    for name, content in files.items():
        assert content == (GOLDEN / name).read_bytes(), name

def test_build_is_deterministic(archive, clock):
    inputs = build_fixture(archive, clock)
    assert build_dataset(inputs) == build_dataset(inputs)

def test_references_hold(archive, clock):
    files = build_dataset(build_fixture(archive, clock))
    ids = {r["variable_id"] for r in read_rows(files["variables.csv"])}
    for t in TABLES:
        for c in t.columns:
            if c.references == "variables.csv.variable_id":
                assert {r[c.name] for r in read_rows(files[t.file])} - {""} <= ids, (t.file, c.name)

def test_no_names_or_notes_leave(archive, clock):
    blob = b"".join(build_dataset(build_fixture(archive, clock)).values())
    for secret in OPERATOR_NAMES + ["secret-note-text"]:
        assert secret.encode() not in blob

def test_holdouts_before_and_after_freeze(archive, clock):
    inputs = build_fixture(archive, clock)
    files = build_dataset(inputs)
    meta = json.loads(files["croissant.json"])
    counts = {p["name"]: p["value"] for p in meta["additionalProperty"]}
    assert counts["excluded_at_freeze"] == inputs.data.manifest["measurements_excluded"] > 0
    assert counts["withheld_at_export"] > 0
    withheld = {(r["holdout_id"], r["batch"]) for r in read_rows(files["withheld.csv"])}
    assert {(h.holdout_id, b) for h in inputs.holdouts for b in h.batch_ids} <= withheld
    measured = {r["record_id"] for r in read_rows(files["measurements.csv"])}
    assert measured.isdisjoint(HELD_RECORD_IDS)

def test_croissant_required_fields(archive, clock):
    inputs = build_fixture(archive, clock)
    files = build_dataset(inputs)
    meta = json.loads(files["croissant.json"])
    assert meta["conformsTo"] == "http://mlcommons.org/croissant/1.1"
    for key in ("name", "description", "license", "url", "creator", "datePublished", "distribution"):
        assert meta[key]
    assert meta["about"] == {"@id": inputs.protocol.crop_taxon}
    for obj in meta["distribution"]:
        assert obj["sha256"] == hashlib.sha256(files[obj["contentUrl"]]).hexdigest()

@pytest.mark.parametrize("change", [{"licence": " "}, {"creator": ""}])
def test_blank_licence_or_creator_is_refused(archive, clock, change):
    with pytest.raises(ExportRefused):
        build_dataset(dataclasses.replace(build_fixture(archive, clock), **change))

def test_protocol_without_crop_taxon_is_refused(archive, clock):
    inputs = build_fixture(archive, clock)
    with pytest.raises(ExportRefused, match="crop_taxon"):
        build_dataset(dataclasses.replace(inputs, protocol=inputs.protocol.model_copy(update={"crop_taxon": ""})))
```

Adjust key spellings (`conformsTo` vs `dct:conformsTo`) to the form the Croissant 1.1 context uses; the value is fixed.

`test_dataset_croissant_reads.py`: write the files to `tmp_path`, load `mlcroissant.Dataset(jsonld=tmp_path / "croissant.json")`, and for every record set assert that the number of records equals the CSV's data rows.

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/dataset`
Expected: FAIL

- [ ] **Step 3: Implement `build.py` and `croissant.py`, then generate the golden files once**

Write `build_dataset(build_fixture(...))` to `tests/dataset/golden/`. Then read every golden file against spec §8 and §11, column by column, before committing. Report anything that looks wrong instead of committing it.

- [ ] **Step 4: Install the dev extra and run them**

Run: `.venv/bin/pip install -e '.[dev]'` then `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/dataset`
Expected: PASS. If no `mlcroissant` release installs on Python 3.11 or reads Croissant 1.1, stop and report BLOCKED. Never skip the test.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/growbridge/dataset tests/dataset tests/dataset_support.py
git commit -m "feat: build the training dataset with Croissant metadata"
```

---

### Task 7: The `export-dataset` command, and retiring `export_miappe`

**Files:**
- Create: `src/growbridge/dataset/command.py`
- Modify: `src/growbridge/cli.py` (subparser and dispatch)
- Modify: `src/growbridge/workflow/store.py` (add `round_ids_of_experiment`)
- Delete: `src/growbridge/archive/export.py`, `tests/archive/test_archive_export.py`
- Test: `tests/dataset/test_dataset_command.py`

**Interfaces:**
- Consumes: `build_dataset`, `ExportInputs`, `read_snapshot`, `load_or_create_key`, `Pseudonymizer`; `Database`, `Archive`, `WorkflowStore`, `HoldoutRegistry`, `packaged_catalog`, `SystemClock`.
- Produces:
  - `WorkflowStore.round_ids_of_experiment(experiment_id: str) -> tuple[str, ...]`: the distinct round ids of the stages that run the experiment, in `rowid` order.
  - `@dataclass(frozen=True) class ExportSummary: out: Path; rows: Mapping[str, int]; counts: Mapping[str, int]`.
  - `export_dataset(data_dir: Path, snapshot_id: str, out: Path, licence: str, creator: str, url: str | None, software_version: str) -> ExportSummary`.
- CLI: `growbridge export-dataset --snapshot ID --out DIR --licence TEXT --creator TEXT [--url URL]`.
  - Success: prints the summary as JSON (`ensure_ascii=False, indent=2`) and exits 0.
  - `ExportRefused`: prints `export refused: <message>` to stderr and exits 1.

`export_dataset`:
1. **Check `out`.** Refuse when it exists, when its parent is missing, or when `out.resolve()` is inside `data_dir.resolve()`.
2. **Open the databases.** Refuse when any of `archive.sqlite3`, `workflow.sqlite3` or `agents.sqlite3` is missing from `data_dir`: opening one would create it, and a missing holdout registry must fail closed rather than export without holdouts. Then open them as `Database(data_dir / f"{name}.sqlite3")`, the way `runtime.py` names them, and the archive root at `data_dir / "archive"`. Close them in `finally`.
3. **Read the snapshot** with `read_snapshot`.
4. **Resolve the experiment.** Each of these must find exactly one entry, else refuse and name what was found (Review Focus 1):
   - project: `projects_of_experiment`;
   - protocol version: `protocol_versions_of`, then `store.protocol(id, version)`;
   - round: `round_ids_of_experiment`, then `store.round_number`.
5. **Holdouts and filter.** Use `HoldoutRegistry(agents_db, SystemClock(), None, catalog).holdouts(project_id)` and `.development_filter(project_id)`.
6. **Records corrected after the freeze.** These are the snapshot measurement ids that some archive record outside the snapshot corrects: `archive.measurements(experiment_id, include_corrected=True)` where `corrects` is in the snapshot's ids and `id` is not.
7. **Pseudonym key** from `data_dir / "export" / "pseudonym.key"`.
8. **Write the files.** Build, then write into `out.parent / f".{out.name}.partial-{secrets.token_hex(4)}"`. Rename it to `out` when complete; remove the partial directory on any error.

- [ ] **Step 1: Write the failing tests** (build the data directory with the existing workflow test helpers that create a project, protocol, round and stage, plus a frozen snapshot; do not insert rows with raw SQL)

```python
def test_export_writes_the_dataset(data_dir, snapshot_id, tmp_path):
    summary = export_dataset(data_dir, snapshot_id, tmp_path / "out", "CC-BY-4.0", "Lab", None, "0.0.0-test")
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == sorted([t.file for t in TABLES] + ["croissant.json"])
    assert summary.rows["measurements.csv"] >= 1 and set(summary.counts) == set(COUNT_NAMES)

def test_export_writes_nothing_but_the_key(data_dir, snapshot_id, tmp_path):
    before = dumps(data_dir)  # iterdump of each sqlite db + sha256 of every snapshot file
    export_dataset(data_dir, snapshot_id, tmp_path / "out", "CC-BY-4.0", "Lab", None, "0.0.0-test")
    assert dumps(data_dir) == before
    assert (data_dir / "export" / "pseudonym.key").exists()

@pytest.mark.parametrize("where", ["exists", "inside_data_dir", "missing_parent"])
def test_bad_out_is_refused(data_dir, snapshot_id, tmp_path, where):
    out = {"exists": tmp_path, "inside_data_dir": data_dir / "out", "missing_parent": tmp_path / "no" / "out"}[where]
    with pytest.raises(ExportRefused):
        export_dataset(data_dir, snapshot_id, out, "CC-BY-4.0", "Lab", None, "0.0.0-test")
    assert not (data_dir / "out").exists() and not (tmp_path / "no").exists()

def test_experiment_in_two_rounds_is_refused(...):  # second round with a stage on the same experiment
    with pytest.raises(ExportRefused, match="round"):
        ...

def test_failed_write_leaves_nothing_behind(monkeypatch, data_dir, snapshot_id, tmp_path):
    # make the file writer raise OSError on the second file, after the partial directory exists
    ...
    with pytest.raises(OSError):
        export_dataset(data_dir, snapshot_id, tmp_path / "out", "CC-BY-4.0", "Lab", None, "0.0.0-test")
    assert not (tmp_path / "out").exists()
    assert not any(p.name.startswith(".out.partial") for p in tmp_path.iterdir())

def test_missing_database_is_refused_and_not_created(data_dir, snapshot_id, tmp_path):
    (data_dir / "agents.sqlite3").unlink()
    with pytest.raises(ExportRefused, match="agents.sqlite3"):
        export_dataset(data_dir, snapshot_id, tmp_path / "out", "CC-BY-4.0", "Lab", None, "0.0.0-test")
    assert not (data_dir / "agents.sqlite3").exists()

def test_cli_reports_a_refusal(capsys, ...):  # main() with argv for an unknown snapshot
    with pytest.raises(SystemExit) as exit_info:
        main_with(["export-dataset", "--snapshot", "snap-missing", ...])
    assert exit_info.value.code == 1 and "export refused" in capsys.readouterr().err
```

`main_with(argv)` is a local helper. It writes a config whose data directory is the fixture's `data_dir`, the way the existing CLI tests do, sets `sys.argv` with `monkeypatch`, and calls `growbridge.cli.main()`.

Also cover the snapshot-level refusals of spec §7 that Tasks 4 and 6 do not: an unknown snapshot through the command, and a measurement unit mismatch through the command.

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/dataset/test_dataset_command.py`
Expected: FAIL

- [ ] **Step 3: Implement the store method, `command.py`, and the CLI wiring.** Delete `archive/export.py` and its test. `git grep -n export_miappe -- src tests` must then print nothing; the docs are Task 8.

- [ ] **Step 4: Run the full suites**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider` and `node --test tests/web/*.test.mjs`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "feat: export-dataset command; retire export_miappe"
```

---

### Task 8: Documentation

**Files:**
- Modify: `docs/wiki/en/Data-Archive-and-Traceability.md` and `docs/wiki/zh-CN/Data-Archive-and-Traceability.md`. Around line 92, `export_miappe` is listed among the functions that verify first. Lines 102–105 hold the MIAPPE row and paragraph. Both become the new export.
- Modify: `docs/wiki/{en,zh-CN}/Variable-Catalog.md`: the term-filling procedure (spec §5.2), CURIE prefixes, `[unit_refs]`.
- Modify: `docs/wiki/{en,zh-CN}/CLI-Reference.md`: the `export-dataset` command, its arguments, refusals and exit codes.
- Create: `docs/wiki/{en,zh-CN}/Training-Dataset-Export.md`. It covers:
  - the purpose;
  - every table and column;
  - `time_source` and `stuck`;
  - what each device-state key means;
  - withheld vs missing;
  - pseudonyms, and what deleting the key does;
  - that notes are not exported;
  - the free-text warning of spec §16.4.
- Modify: `docs/wiki/{en,zh-CN}/_Sidebar.md`, and the glossary if it lists export terms.
- Test: `tests/docs/test_docs_wiki.py` (existing)

- [ ] **Step 1: Write the pages.** Every claim is checked against the code from Tasks 1–7, with links to the source files, as the existing pages do.
- [ ] **Step 2: Run the wiki tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/docs`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add docs/wiki
git commit -m "docs: training dataset export, catalog terms and the CLI command"
```

---

### Task 9: Ontology terms (needs the user)

**Files:**
- Create: `docs/superpowers/notes/2026-11-18-ontology-candidates.md`
- Modify (after confirmation only): `src/growbridge/vocab/catalog.toml`, `src/growbridge/vocab/catalog.lock.json`

**Interfaces:**
- Consumes: the CURIE rules and `[unit_refs]` from Task 1.

- [ ] **Step 1: Prepare candidates.** For each of the 8 catalog entries and each unit they use, look up candidates on OLS (https://www.ebi.ac.uk/ols4) or AgroPortal. Write one table row per candidate:
  - entry id;
  - CURIE;
  - term label;
  - the term's definition, quoted at most one sentence;
  - ontology and its version or the lookup date;
  - why it fits.

  Mark an entry "no fitting term" rather than stretch one. Do not touch the catalog.
- [ ] **Step 2: Commit the candidates file**

```bash
git add docs/superpowers/notes/2026-11-18-ontology-candidates.md
git commit -m "docs: ontology term candidates for the catalog"
```

- [ ] **Step 3: Stop.** The controller shows the file to the user and asks them to confirm or reject each row. Nothing is written to the catalog without the user's answer, quoted in the ledger.
- [ ] **Step 4: Write the confirmed terms.**
  - Put them into `refs` and `[unit_refs]` and set `version = 2`.
  - Add the v2 digest to `catalog.lock.json`'s `versions`. The entry digests are unchanged; the lock test prints the lines to add.
  - Update `test_packaged_catalog_is_unchanged` from Task 1 to expect version 2 and the confirmed `unit_refs`.
  - Regenerate the golden files only where `refs`/`unit_uo` changed, and check the diff is only those columns.
- [ ] **Step 5: Run the full suite and commit**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider`
Expected: PASS

```bash
git add src/growbridge/vocab tests
git commit -m "feat: confirmed ontology terms for the catalog (version 2)"
```
