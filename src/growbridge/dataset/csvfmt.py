"""CSV cell format and writer: UTF-8, LF, sorted rows, UTC times, empty field for none."""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

from growbridge.dataset.schema import DataType, Table


def format_time(seconds: float) -> str:
    stamp = datetime.fromtimestamp(seconds, UTC).isoformat(timespec="milliseconds")
    return stamp.replace("+00:00", "Z")


def format_cell(value: object, data_type: DataType) -> str:
    if value is None:
        return ""
    if data_type == "Boolean":
        return "true" if value else "false"
    if data_type == "Integer":
        return str(int(value))  # type: ignore[call-overload]
    if data_type in ("Float", "DateTime"):
        number = float(value)  # type: ignore[arg-type]
        if not math.isfinite(number):
            return ""
        return format_time(number) if data_type == "DateTime" else repr(number)
    return repr(value) if isinstance(value, float) else str(value)


def write_csv(table: Table, rows: Iterable[Mapping[str, object]]) -> bytes:
    names = [column.name for column in table.columns]
    known = set(names)
    materialised = list(rows)
    for row in materialised:
        unknown = set(row) - known
        if unknown:
            raise ValueError(f"{table.file}: unknown columns {sorted(unknown)}")

    def order(row: Mapping[str, object]) -> list[tuple[bool, object]]:
        return [(row.get(key) is not None, row.get(key)) for key in table.sort_key]

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(names)
    for row in sorted(materialised, key=order):
        writer.writerow(format_cell(row.get(c.name), c.data_type) for c in table.columns)
    return out.getvalue().encode("utf-8")
