"""Stable identifiers and content digests for archive records."""

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

CHUNK_BYTES = 1 << 20


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def canonical_json(obj: Any) -> str:
    """One JSON text per value: sorted keys, no padding, unicode kept readable."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_digest(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()


def file_digest(path: Path | str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()
