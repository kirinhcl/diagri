# Training dataset export

[简体中文](../zh-CN/Training-Dataset-Export.md)

This page is for the people who take DiAGRI data into a crop foundation model. It explains what `growbridge export-dataset` writes from one frozen snapshot: eleven CSV tables and a Croissant description, where every column comes from, and what the numbers do and do not mean. The command's options and exit codes are in the [CLI reference](CLI-Reference.md#export-dataset).

## Purpose

One export is one verified snapshot of one experiment, written in a form that other teams can merge with data from other sources. The tables are long format (one row per reading), so a new sensor key adds rows, not columns. Times are UTC. Nothing in the output names a person: operators appear only as pseudonyms.

The export reads the snapshot's own files, so it carries what the snapshot froze. Three things come from the live databases and not from the snapshot: the protocol and its design, the holdout registry as it is now, and the list of measurements corrected after the freeze. The column list is in [`dataset/schema.py`](../../../src/growbridge/dataset/schema.py), the single source for both the CSV files and `croissant.json`.

## What the command writes

Into the new directory `--out`:

| File | One row per |
| --- | --- |
| `variables.csv` | variable the data uses |
| `treatments.csv` | treatment and factor |
| `units.csv` | experimental unit in a round |
| `sensor_readings.csv`, `sensor_readings_untrusted.csv` | sensor key in a sample |
| `device_states.csv`, `device_states_untrusted.csv` | actuator state key in a sample |
| `measurements.csv` | manual measurement (the latest version of each) |
| `actions.csv` | actuation request |
| `interventions.csv` | intervention |
| `withheld.csv` | held-out batch and outcome variable |
| `croissant.json` | the description of all of the above |

The files are written to a temporary directory next to `--out` and renamed when all are complete, so a failed export leaves no half-written directory. The format is the same every time: UTF-8, LF line endings, a header row, times as UTC ISO 8601 with milliseconds and a trailing `Z`, an empty field for "none", rows sorted by each table's key ([`dataset/csvfmt.py`](../../../src/growbridge/dataset/csvfmt.py)). The same snapshot, catalog, holdout registry, pseudonym key and arguments give byte-identical files, as long as no new correction of a snapshot record is recorded in between: `corrected_after_freeze` is read from the live archive, not from the snapshot, so such a correction changes `croissant.json`.

### Do not open the CSV files in a spreadsheet

The CSV files are training data for machines and are written faithfully, without any escaping. Text that operators typed (`plant_id`, `batch`, `position` and the like) is not neutralised against spreadsheet formulas, so a cell that starts with `=`, `+`, `-` or `@` could be run as a formula. Do not open the files directly in a spreadsheet application. Read them with code, or import them into a spreadsheet with every column set to text.

## The tables

Column types are `Text`, `Float`, `Integer`, `Boolean` (`true` or `false`) and `DateTime`. A field is empty when the value is none or, for a float, not finite.

### Sensor and device readings

Both pairs of tables start with the same columns:

| Column | Meaning |
| --- | --- |
| `time` | Time of the reading. |
| `time_source` | `captured` when the device gave a capture time on a synchronised clock; otherwise `received`, the time the bridge received the reading. |
| `clock_synced` | True when the device clock was synchronised when it reported. |
| `sample_id` | The sample the reading came from; groups readings. |
| `device_id` | Device that produced the reading. |
| `experiment_id`, `stage_id`, `round` | Where the reading falls in the experiment; empty when none. |

`sensor_readings.csv` adds `variable_id` (the catalog variable the key resolved to; empty when none, which counts as an unresolved sensor key), `raw_key` (the key exactly as the controller reports it), `value` (in the variable's unit `unit_ucum`), `quality` (the controller's flag; empty when none) and `stuck`.

`device_states.csv` adds `key`, `value` and `quality`.

**`time_source`.** Do not mix the two clocks without looking at this column: a received time includes the delay between the device and the bridge, and a device clock that was not synchronised is not a reliable time. Filter or model on `time_source` and `clock_synced` rather than assuming one.

**`stuck`.** True when the reading falls inside a period in which that sensor kept reporting exactly the same value (a frozen sensor), taken from the snapshot's `frozen_periods.jsonl`; a period that has not closed yet runs to the end. The periods are compared with the sample's capture time whenever the device gave one, which is the time the frozen-reading check records them on, even when the clock was not synchronised and `time` is the received time. Such a reading looks normal and is unreliable.

**Trusted and untrusted.** A sample is trusted when its clock is synchronised, its quality is `ok` and its source is `planned`. Trusted samples go to the plain tables. The others go to the `_untrusted` tables, which have the same columns; they are kept for inspection and are not training data. See [Data, archive and traceability](Data-Archive-and-Traceability.md#how-a-data-snapshot-is-frozen-and-verified).

**Values that are not numbers.** A sensor or device value that is not a number (text, a boolean, none) is not a row; it is counted as `non_numeric_values`. A sample whose `sensor` value is there but is not an object gives no sensor rows and counts once. A number that is not finite (`nan`, `inf`) is a row with an empty `value`.

### Device-state keys

The `key` column holds the keys the controller reports. They are exported as they are; the meaning of each is below, taken from the commands DiAGRI sends ([`mcp_server.py`](../../../src/growbridge/mcp_server.py)). No unit is given because the code gives none.

| Key | Values |
| --- | --- |
| `light.level` | 0 to 100: manual light brightness on the scale of the level DiAGRI commands; 0 is off. |
| `fan.level` | 0 to 10: circulation fan manual gear on the scale of the level DiAGRI commands; 0 is off. |
| `blower.level` | 0 to 100: manual speed of the exhaust blower; 0 is off. |
| `light.on`, `fan.on`, `blower.on` | 0 or 1. |
| `outlet.O1.on` to `outlet.O5.on` | 0 or 1. |

### `variables.csv`

One row for each variable the exported rows refer to, plus every variable the protocol declares. The entry is the one the snapshot froze; the ontology columns come from the catalog as it is now.

| Column | Meaning |
| --- | --- |
| `variable_id` | Stable identifier. |
| `kind` | `sensor`, `manual` or `factor`. |
| `label_en`, `quantity`, `method` | English label, the quantity measured, how it is measured (empty when unspecified). |
| `unit_ucum` | Unit as a UCUM code. |
| `unit_uo` | Unit as a Units Ontology term; empty until confirmed. |
| `min`, `max` | Plausible range in `unit_ucum`; empty when unbounded. |
| `refs` | Ontology terms as space-separated CURIEs; empty until confirmed. |
| `mapped` | True when `refs` holds at least one term. |

Unmapped variables are exported with `mapped=false` and counted in `unmapped_variables`. The terms are filled in by the researcher, one by one: see [Variable catalog](Variable-Catalog.md#ontology-terms).

### `treatments.csv` and `units.csv`

`treatments.csv`: `treatment_id`, `name`, `is_control`, `variable_id` (the factor) and `value` (as text, since a factor may be a string). A treatment with several factors has several rows; one without factors has one row with empty `variable_id` and `value`.

`units.csv`: `round`, `block` (empty when the design has no blocks), `unit` and `treatment_id`. It says which treatment each unit received. Its key is `round` and `unit` together.

### `measurements.csv`

`time`, `record_id`, `corrects` (the `record_id` this record corrects), `experiment_id`, `round`, `batch`, `unit`, `treatment_id`, `plant_id`, `position`, `layout_version`, `variable_id`, `value`, `method` and `operator`. Only the latest version of each measurement is a row; the records it replaced are counted as `superseded_records`. `unit` and `treatment_id` come from the position, through the design in the protocol. A position that matches no unit gives empty `unit` and `treatment_id` and is counted as `unplaced_measurements`.

A measurement is refused (the whole export is refused) when its name is not in the catalog or its unit differs from the catalog's.

### `actions.csv` and `interventions.csv`

`actions.csv`: `request_id`, `channel`, `state`, `trigger`, `planned_level`, `confirmed_level`, `created_at`, `sent_at`, `confirmed_at`, `ran_seconds`, `error_code`, `ended_early_code`, `supersedes` and `operator`. The `trigger` is cleaned: see [Free text](#free-text-and-names).

`interventions.csv`: `id`, `time`, `stage_id`, `kind`, `detail` (what the system recorded, as JSON with sorted keys) and `operator`.

### `withheld.csv`

`holdout_id`, `batch` and `variable_id`. See the next section.

## Withheld is not missing

A holdout keeps a batch's outcomes back for testing a model later (see [Research methodology](Research-Methodology.md#holdout-data-for-prediction-models)). In the export these outcomes are absent from `measurements.csv` by design, not at random, and `withheld.csv` lists them: one row per held-out batch and outcome variable, with `variable_id` set to `*` when the holdout withholds all outcome variables or names one the catalog cannot resolve. Treat a batch listed there as test data held back elsewhere, not as a batch with missing values.

The export applies the holdout registry as it is now, not as it was when the snapshot was frozen. A holdout registered after the snapshot was frozen still keeps its outcomes out; the rows it removes are counted as `withheld_at_export`, and those removed at freeze time as `excluded_at_freeze`. Only the outcomes are held out: the same batches' sensor data and their non-outcome measurements are still exported.

## Pseudonyms

Every `operator` value is `op-` followed by 12 hexadecimal characters: an HMAC-SHA-256 of the name under a key, cut short ([`dataset/pseudonym.py`](../../../src/growbridge/dataset/pseudonym.py)). The key is the file `<data_dir>/export/pseudonym.key`, 32 random bytes with mode 0600, created on the first export. It is the only thing the export writes into the data directory.

- One installation gives one person one pseudonym in every export, so the same person can be followed across exports.
- The names cannot be looked up from the output. Without the key they cannot be recomputed either.
- Deleting the key breaks that link: the next export creates a new key and gives every person a new pseudonym, and the old and new exports cannot be joined on `operator`. Keep the key if you will export again. The key is not part of the dataset: do not share it.
- The daemon's backups copy the databases only ([Backup](Data-Archive-and-Traceability.md#backup)), not `export/pseudonym.key`. A data directory restored without the key gives every person a new pseudonym in the next export. Back the key up separately, and keep that copy as private as the key itself.

## Free text and names

Operator notes are not exported. A note can hide in an action's `trigger`, so the trigger is cleaned: the notes of `manual` and `planned irrigation <id>` triggers are cut off (counted as `notes_dropped`), and a trigger of a form the cleaner does not know becomes `other` (counted as `other_triggers`), so a new format cannot leak a note ([`dataset/triggers.py`](../../../src/growbridge/dataset/triggers.py)).

Some free text is data and is exported as typed: `batch`, `plant_id`, `position`, `layout_version` and `method` in `measurements.csv`, the treatment `name` in `treatments.csv`, and the protocol's question and hypothesis, which form the dataset description in `croissant.json`. Nothing cleans these. **Tell data-entry users not to put people's names in these fields.**

## `croissant.json`

The metadata follows Croissant 1.1 and conforms to `http://mlcommons.org/croissant/1.1`. [`dataset/croissant.py`](../../../src/growbridge/dataset/croissant.py) builds it.

- **Dataset fields.** `name` is `diagri-<snapshot id>`; `description` is the protocol's question and hypothesis; `license` and `creator` are the command's `--licence` and `--creator` (the creator is recorded as an `sc:Organization`, a creator shape mlcroissant accepts; the other is `sc:Person`); `url` is `--url` or `urn:diagri:snapshot:<id>`; `datePublished` is the UTC date the snapshot was created; `about` is the crop species `crop_taxon`.
- **Files.** One `FileObject` per CSV, with its SHA-256, and one `RecordSet` per table with a `Field` per column, its type and its description.
- **References.** Only `variable_id` columns carry a Croissant `references`, to `variables.csv`, whose key it is. `treatment_id` and `unit` name their source in the field description instead: `treatments.csv` has one row per treatment and factor, and `units.csv` is keyed by `round` and `unit` together, so a join on either would multiply records.
- **Provenance.** `prov:wasDerivedFrom` names the snapshot and the SHA-256 of its manifest; `prov:wasGeneratedBy` names `growbridge`, its version and the command.
- **Counts.** `additionalProperty` holds the counts below, the `cultivar`, `facility_type`, the snapshot's coverage and gaps, `snapshot_catalog_version` and `current_catalog_version`, and `corrected_after_freeze_ids`.

| Count | Meaning |
| --- | --- |
| `unmapped_variables` | Rows of `variables.csv` with `mapped=false`. |
| `unresolved_sensor_keys` | Sensor rows whose key resolved to no catalog variable. |
| `non_numeric_values` | Sensor and device values that were not numbers and are not rows. |
| `excluded_at_freeze` | Outcome measurements left out when the snapshot was frozen. |
| `withheld_at_export` | Measurements left out now by the holdout registry. |
| `superseded_records` | Measurements replaced by a correction in the snapshot. |
| `corrected_after_freeze` | Snapshot measurements corrected after the freeze; the export has the value as frozen. |
| `notes_dropped` | Operator notes cut from triggers. |
| `other_triggers` | Triggers exported as `other`. |
| `unplaced_measurements` | Measurements whose position matched no unit. |

## Crop species

`croissant.json` names the crop through the protocol. A new protocol version must give `crop_taxon` as `NCBITaxon:<number>`, an NCBI Taxonomy ID; `cultivar` is optional, at most 200 characters. Saving a version that does not is refused with `protocol_crop_taxon_invalid`, and the workbench's protocol form has both fields. Protocols saved earlier have no species and cannot be exported; use the new version for the next round.

## Read-only, and when it refuses

The export only reads the archive, workflow and agents databases and the snapshot directory, and writes nothing in the data directory except the pseudonym key (which may already exist when a later check refuses the export). It does not take the daemon lock, so it can run while the daemon runs. It refuses, with a message, when the schema of the data directory is older than the installed growbridge (start the daemon once with the new version, then export), when a database file is missing, when a database is busy (try again), and when SQLite cannot read a database (the message gives SQLite's error). The full list is in the [CLI reference](CLI-Reference.md#export-dataset).

## See also

- [CLI reference](CLI-Reference.md#export-dataset)
- [Variable catalog](Variable-Catalog.md)
- [Data, archive and traceability](Data-Archive-and-Traceability.md)
- [Research methodology](Research-Methodology.md)
