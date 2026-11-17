"""What an attempt's error says besides its English text: a message code and its params.

The English ``error`` column stays as it was written; ``error_code`` and ``error_params`` sit
beside it (see ``growbridge.codes``, family ``compute_error``). An attempt stored before codes
existed has ``error_code == ''``: no code, only the English text.
"""

import json
from collections.abc import Mapping
from typing import Any, NamedTuple

from growbridge.codes import checked

OUTPUT_LIMIT_MARK = "output limit:"  # how an oversized fetch was written before it had a code
OUTPUT_LIMIT = "output_limit"
TOO_MANY_FILES = "too_many_files"
OUTPUT_LIMIT_CODES = frozenset({OUTPUT_LIMIT, TOO_MANY_FILES})  # a fetch refused for its size
CLEARED: dict[str, str] = {"error": "", "error_code": "", "error_params": "{}"}


class Problem(NamedTuple):
    """One thing wrong with a fetched file: its English text, code and params."""

    text: str
    code: str
    params: Mapping[str, Any]


def coded(code: str, params: Mapping[str, Any] | None = None) -> dict[str, str]:
    """The ``error_code`` and ``error_params`` columns for a code of the compute_error family."""
    kept = checked("compute_error", code, params or {})
    return {"error_code": code, "error_params": json.dumps(kept, sort_keys=True)}


def is_output_limit(error: str, error_code: str) -> bool:
    """Whether the attempt's error is a fetch refused for its size (old rows: by the prefix)."""
    if error_code:
        return error_code in OUTPUT_LIMIT_CODES
    return error.startswith(OUTPUT_LIMIT_MARK)
