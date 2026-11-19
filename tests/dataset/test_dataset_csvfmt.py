import csv
import io

import pytest

from growbridge.dataset.csvfmt import format_cell, format_time, write_csv
from growbridge.dataset.schema import Column, Table


def test_format_time():
    assert format_time(0.0) == "1970-01-01T00:00:00.000Z"
    assert format_time(1700000000.1234) == "2023-11-14T22:13:20.123Z"


def test_format_cell():
    assert format_cell(None, "Float") == ""
    assert format_cell(0.1, "Float") == "0.1" and format_cell(3, "Float") == "3.0"
    assert format_cell(True, "Boolean") == "true" and format_cell(7, "Integer") == "7"
    assert format_cell(False, "Boolean") == "false"
    assert format_cell(0.0, "DateTime") == "1970-01-01T00:00:00.000Z"
    assert format_cell(1.5, "Text") == "1.5" and format_cell("x", "Text") == "x"
    assert format_cell(2, "Text") == "2"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_floats_are_empty(value):
    assert format_cell(value, "Float") == ""


def test_text_round_trips():
    t = Table("x.csv", "", (Column("a", "Text", ""), Column("b", "Float", "")), ("a",))
    text = 'A,"1"\n二'
    data = write_csv(t, [{"a": text, "b": 1.5}])
    assert b"\r" not in data and data.endswith(b"\n")
    assert list(csv.reader(io.StringIO(data.decode("utf-8")))) == [["a", "b"], [text, "1.5"]]


def test_rows_sorted_with_none_first():
    t = Table("x.csv", "", (Column("a", "Text", ""),), ("a",))
    # Python's csv writes a row whose only field is empty as "" (an empty line would read as no row)
    assert write_csv(t, [{"a": "b"}, {"a": None}, {"a": "a"}]) == b'a\n""\na\nb\n'


def test_unknown_column_is_an_error():
    t = Table("x.csv", "", (Column("a", "Text", ""),), ("a",))
    with pytest.raises(ValueError):
        write_csv(t, [{"a": "x", "zz": 1}])
