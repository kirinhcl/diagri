"""Stable operator pseudonyms: a keyed hash, so names cannot be looked up from the output."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path

KEY_BYTES = 32


def load_or_create_key(path: Path) -> bytes:
    """Read the pseudonym key, creating it (mode 0600) on first use."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        key = path.read_bytes()
        if len(key) != KEY_BYTES:
            raise ValueError(f"{path} must hold {KEY_BYTES} bytes, found {len(key)}") from None
        return key
    key = secrets.token_bytes(KEY_BYTES)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(key)
    return key


class Pseudonymizer:
    def __init__(self, key: bytes) -> None:
        self._key = key

    def __call__(self, name: str | None) -> str | None:
        if name is None:
            return None
        digest = hmac.new(self._key, name.encode("utf-8"), hashlib.sha256).hexdigest()
        return "op-" + digest[:12]
