"""Read archived samples of one experiment in time buckets, counting the flagged ones."""

from __future__ import annotations

import json

from growbridge.archive.db import Database

DEFAULT_POINTS = 600
MAX_POINTS = 2000

# One row per bucket: the newest sample's rowid, how many samples fell in the bucket and how
# many of them are not plain "ok" or were stamped by an unsynchronised clock.
_BUCKETS = """
SELECT MAX(rowid) AS pick, COUNT(*) AS n,
       SUM(json_extract(body, '$.quality') != 'ok'
           OR json_extract(body, '$.clock_synced') = 0) AS flagged
FROM samples WHERE experiment_id = ? AND at BETWEEN ? AND ?
GROUP BY CAST((at - ?) / ? AS INTEGER)
"""


def bucketed_samples(
    db: Database, experiment_id: str, start: float, end: float, points: int
) -> dict:
    """Keep the last sample of each time bucket; report what the thinning hid."""
    bucket = max(1.0, (end - start) / points)
    buckets = db.query(_BUCKETS, (experiment_id, start, end, start, bucket))
    flagged_by_pick = {row["pick"]: int(row["flagged"] or 0) for row in buckets}
    samples = [_sample(db, pick, flagged) for pick, flagged in flagged_by_pick.items()]
    samples.sort(key=lambda sample: sample["timestamp"])
    total = sum(row["n"] for row in buckets)
    return {
        "samples": samples,
        "window": {"start": start, "end": end, "bucket_seconds": bucket},
        "total_samples": total,
        "flagged_total": sum(flagged_by_pick.values()),
        "downsampled": total > len(samples),
    }


def _sample(db: Database, rowid: int, flagged: int) -> dict:
    row = db.one("SELECT at, body FROM samples WHERE rowid = ?", (rowid,))
    body = json.loads(row["body"])
    return {
        "timestamp": row["at"],
        "data": body.get("data", {}),
        "quality": body.get("quality", "ok"),
        "clock_synced": bool(body.get("clock_synced", True)),
        "flagged": flagged,
    }
