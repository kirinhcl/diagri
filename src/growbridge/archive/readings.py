"""Read archived samples of one experiment in time buckets, counting the flagged ones."""

from __future__ import annotations

import json

from growbridge.archive.db import Database

DEFAULT_POINTS = 600
MAX_POINTS = 2000
MIN_POINTS = 2

# One row per bucket: the newest sample's rowid, how many samples fell in the bucket and how
# many of them are not plain "ok" or were stamped by an unsynchronised clock. Joined back to
# the samples table so every picked row comes out in the same single query.
_PICKED = """
SELECT s.at AS at, s.body AS body, b.n AS n, b.flagged AS flagged
FROM samples s JOIN (
    SELECT MAX(rowid) AS pick, COUNT(*) AS n,
           SUM(json_extract(body, '$.quality') != 'ok'
               OR json_extract(body, '$.clock_synced') = 0) AS flagged
    FROM samples WHERE experiment_id = ? AND at BETWEEN ? AND ?
    GROUP BY CAST((at - ?) / ? AS INTEGER)
) b ON s.rowid = b.pick
ORDER BY s.at
"""


def bucketed_samples(
    db: Database, experiment_id: str, start: float, end: float, points: int
) -> dict:
    """Keep the last sample of each time bucket; report what the thinning hid."""
    points = max(MIN_POINTS, min(int(points), MAX_POINTS))
    bucket = max(1.0, (end - start) / points)
    window = {"start": start, "end": end, "bucket_seconds": bucket}
    if end <= start:
        return _result([], window, 0, 0)
    rows = db.query(_PICKED, (experiment_id, start, end, start, bucket))
    samples = [_sample(row) for row in rows]
    flagged_total = sum(int(row["flagged"] or 0) for row in rows)
    return _result(samples, window, sum(row["n"] for row in rows), flagged_total)


def _result(samples: list[dict], window: dict, total: int, flagged_total: int) -> dict:
    return {
        "samples": samples,
        "window": window,
        "total_samples": total,
        "flagged_total": flagged_total,
        "downsampled": total > len(samples),
    }


def _sample(row) -> dict:
    body = json.loads(row["body"])
    return {
        "timestamp": row["at"],
        "data": body.get("data", {}),
        "quality": body.get("quality", "ok"),
        "clock_synced": bool(body.get("clock_synced", True)),
        "flagged": int(row["flagged"] or 0),
    }
