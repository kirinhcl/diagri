"""One way to make an answer's values safe to write as JSON."""

import math


def json_safe(value):
    """``value`` with every NaN or infinity written as text, the only way JSON can carry it, and
    every lone surrogate escaped (``\\ud800``): UTF-8 cannot encode one, and an answer that
    echoes the input back would otherwise fail with 500."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, str):
        return value.encode("utf-8", "backslashreplace").decode("utf-8")
    if isinstance(value, dict):
        return {json_safe(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    return value
