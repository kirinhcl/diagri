"""MIAPPE-compatible metadata export for a frozen snapshot (architecture doc §11.2).

The metadata is built from the snapshot's own files, never the live database, so it describes
exactly the data an analysis used. Each dataset needs a persistent identifier and a licence.
"""

import json
from pathlib import Path

from growbridge.archive.ids import canonical_json
from growbridge.archive.models import ResearchProtocol, Snapshot
from growbridge.archive.snapshot import verify
from growbridge.archive.store import Archive

OUTPUT_NAME = "miappe.json"


def _read_lines(archive: Archive, snapshot: Snapshot, name: str) -> list[dict]:
    path = archive.root / "snapshots" / snapshot.id / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _variables(samples: list[dict], measurements: list[dict]) -> list[dict]:
    manual = {
        (m["metric"], m["unit"], m["method"]): {
            "name": m["metric"],
            "unit": m["unit"],
            "method": m["method"],
            "origin": "manual",
        }
        for m in measurements
    }
    names = sorted({key for s in samples for key in s["data"]})
    sensors = [
        {"name": name, "unit": None, "method": "sensor reading", "origin": "sensor"}
        for name in names
    ]
    return [*(manual[key] for key in sorted(manual)), *sensors]


def _units(protocol: ResearchProtocol) -> list[dict]:
    treatments = {t.id: t for t in protocol.treatments}
    return [
        {
            "unit": a.unit,
            "round": a.round,
            "block": a.block,
            "treatment": treatments[a.treatment_id].name,
            "treatment_id": a.treatment_id,
            "factors": treatments[a.treatment_id].factors,
        }
        for a in protocol.allocations
    ]


def export_miappe(
    archive: Archive,
    snapshot: Snapshot,
    protocol: ResearchProtocol,
    out: Path,
    licence: str,
    identifier: str,
) -> Path:
    """Write ``out/miappe.json`` and return its path."""
    if not licence.strip() or not identifier.strip():
        raise ValueError("a licence and a persistent identifier are required")
    if not verify(archive, snapshot.id):
        raise ValueError(f"snapshot {snapshot.id} failed verification; refusing to export")
    samples = _read_lines(archive, snapshot, "samples.jsonl")
    measurements = _read_lines(archive, snapshot, "measurements.jsonl")
    metadata = {
        "identifier": identifier.strip(),
        "licence": licence.strip(),
        "investigation": {"id": protocol.project_id, "crop": protocol.crop},
        "study": {
            "protocol_id": protocol.id,
            "protocol_version": protocol.version,
            "question": protocol.question,
            "hypothesis": protocol.hypothesis,
            "batch": protocol.batch,
            "randomization_seed": protocol.randomization_seed,
            "primary_endpoint": protocol.analysis.primary_endpoint,
        },
        "experimental_units": _units(protocol),
        "observed_variables": _variables(samples, measurements),
        "snapshot": {
            "id": snapshot.id,
            "version": snapshot.version,
            "created_at": snapshot.created_at,
            "complete": snapshot.complete,
            "coverage": snapshot.coverage,
            "gaps": [list(gap) for gap in snapshot.gaps],
        },
        "data_files": snapshot.files,
    }
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / OUTPUT_NAME
    path.write_text(canonical_json(metadata), encoding="utf-8")
    return path
