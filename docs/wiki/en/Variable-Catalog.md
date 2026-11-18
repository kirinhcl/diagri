# Variable catalog

[简体中文](../zh-CN/Variable-Catalog.md)

This page is for researchers and developers. It explains the shared list of variable names that protocols, measurements, snapshots and holdouts all use, and how to change it.

## What it is for

Every measured quantity and every treatment factor has one standard ID, for example `air_temperature`. Without a shared list, one protocol says `temp`, a measurement says `Temperature` and a script filters on `air temp`, and the data cannot be joined. The catalog gives each variable a standard ID, a kind (`sensor`, `manual` or `factor`), a quantity, a unit, a method and, where it makes sense, the allowed range `min` and `max`.

The catalog is the file [`vocab/catalog.toml`](../../../src/growbridge/vocab/catalog.toml). The runtime loads it once at startup and shares that one instance with the workflow, the run-sheet check and the holdout registry. A broken catalog stops the runtime from starting.

## The append-only rule

An entry's defining fields never change: `id`, `kind`, `quantity`, `unit`, `method`, `min`, `max`. Data recorded under an ID must keep meaning the same thing for ever.

- To add a variable, append an entry and raise `version` in the file.
- To change what a variable means, add a new ID, mark the old one `deprecated = true` and set its `replaced_by` to the new ID.
- A deprecated ID is accepted in a protocol only if an earlier version of the same protocol already declared it.

## The lock file

[`vocab/catalog.lock.json`](../../../src/growbridge/vocab/catalog.lock.json) makes the rule checkable:

- `versions` maps each catalog version to the SHA-256 of the file as it was released.
- `entries` maps each ID to a digest of its defining fields.

After an addition, add the new version's digest and the new entries' digests to the lock. The failing lock tests print the exact lines to add. A changed defining field, or a released version whose file differs, fails the same tests.

## Aliases are device keys only

Only sensor entries have aliases, and they are the device's own sensor keys: `temp`, `humi`, `vpd`, `co2`, `ppfd`, `tempSoil`. An alias lets the bridge's readings resolve to a standard ID. A protocol or a measurement must use the standard ID; an alias there is refused, and the message names the standard ID.

## Ontology terms

The training dataset export ([Training dataset export](Training-Dataset-Export.md)) can describe each variable and unit with ontology terms. They are optional fields of the catalog and are not part of a variable's definition, so adding them does not change the lock digest of an entry.

- `refs` on an entry is a list of CURIEs, for example `PECO:...`. Each must have a known prefix, or the catalog does not load. The prefixes are `PECO`, `ENVO`, `AGRO`, `PATO`, `UO`, `NCBITaxon` and the Crop Ontology crop ontologies `CO_<number>` ([`vocab/curie.py`](../../../src/growbridge/vocab/curie.py)). The export writes each prefix's base address into the `@context` of `croissant.json`.
- `[unit_refs]` is a table in the catalog file. A key is a UCUM unit code some entry uses; the value is the Units Ontology (`UO:`) term for it. Both are checked when the catalog loads ([`vocab/catalog.py`](../../../src/growbridge/vocab/catalog.py)). A unit with no confirmed term is left out.

**Nothing guesses a term.** `refs` and `[unit_refs]` stay empty until the researcher confirms each term. The procedure:

1. Look up candidates for each entry on OLS or AgroPortal and write down the CURIE, the term's label, the ontology and its version or the date of the lookup. Use Crop Ontology variables, traits, methods and scales for manual traits, PECO for treatment factors, and ENVO or AGRO for environmental quantities.
2. The researcher confirms the terms one by one; only the researcher can judge whether a term's definition matches how the variable is measured. Leave an uncertain entry empty.
3. Write the confirmed terms into `catalog.toml`, raise `version`, and add the new version's digest to `versions` in the lock file.

Until then the export lists the variable with `mapped=false` and counts it in `unmapped_variables`, and the `unit_uo` column stays empty.

## Declare variables before the protocol is saved

A research protocol must declare its `variables`, a list of catalog IDs. Saving is refused with 422 `param`, listing every problem, when:

- the list is empty or names an ID twice;
- an ID is not in the catalog, is an alias, or is deprecated and was not declared by an earlier version of this protocol;
- the primary endpoint is not among the declared variables, or is not a manual variable (it is analysed from manual measurements only);
- a treatment's factor key is not a catalog factor ID.

So a new experiment's variables must be in the catalog before its protocol is saved. If one is missing, add it to the catalog first (append-only, new version, lock updated).

## What it controls downstream

- **Measurements.** A manual measurement may only name a variable the experiment's protocols declare, with that variable's unit and inside its range. See [Run a research round](Run-a-Research-Round.md#record-a-measurement).
- **Holdouts.** Outcome names are resolved through the catalog; a name it cannot resolve counts as a held-out outcome. See [Research methodology](Research-Methodology.md#holdout-data-for-prediction-models).
- **Training dataset.** The export writes the catalog's entries, terms and units into `variables.csv`, and the catalog `version` into `croissant.json`.
- **Snapshots.** Each data snapshot contains `catalog.json` with the catalog `version`, its `digest`, the `variables` the data uses and the names that are `unresolved`.

## See also

- [Run a research round](Run-a-Research-Round.md)
- [Research methodology](Research-Methodology.md)
- [HTTP, workbench and MCP interfaces](API-Reference.md)
- [Data, archive and traceability](Data-Archive-and-Traceability.md)
