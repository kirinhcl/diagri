"""Read the wiki's reference pages as data, so tests can hold them against the code.

An English page and its Chinese twin have the same headings in the same order (the wiki's
editing conventions), so a section is found by its English heading and the Chinese section is
the one at the same position.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WIKI = ROOT / "docs" / "wiki"
LANGUAGES = ("en", "zh-CN")
HEADING = re.compile(r"^(#{2,3}) (.+)$", re.MULTILINE)
FENCED_BLOCK = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
FIRST_CELL_CODE = re.compile(r"^\| `([^`]+)` \|", re.MULTILINE)
CODE_SPAN = re.compile(r"`([^`]+)`")


def headings(text: str) -> list[re.Match[str]]:
    """Every level-2 and level-3 heading outside code blocks, in order."""
    # Blank code blocks out without changing any offset, so a match's offsets slice ``text``.
    visible = FENCED_BLOCK.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    return list(HEADING.finditer(visible))


def sections(text: str) -> list[tuple[str, str]]:
    """``(heading, body)`` for every heading of ``headings``; a body runs to the next one."""
    marks = headings(text)
    ends = [m.start() for m in marks[1:]] + [len(text)]
    return [(m.group(2).strip(), text[m.end() : end]) for m, end in zip(marks, ends, strict=True)]


def section_in_each_language(english: Path, chinese: Path, heading: str) -> dict[str, str]:
    """The body under ``heading`` in the English file and the body at the same place in the
    Chinese file, keyed by language. The two files must have the same outline: the same
    number of headings, each at the same level."""
    en_text, zh_text = english.read_text(encoding="utf-8"), chinese.read_text(encoding="utf-8")
    en_levels = [len(m.group(1)) for m in headings(en_text)]
    zh_levels = [len(m.group(1)) for m in headings(zh_text)]
    assert en_levels == zh_levels, f"{english.name}: the two languages have different outlines"
    en, zh = sections(en_text), sections(zh_text)
    index = [title for title, _ in en].index(heading)
    return {"en": en[index][1], "zh-CN": zh[index][1]}


def wiki_section(page: str, heading: str) -> dict[str, str]:
    """``heading``'s section of the wiki page ``page`` in both languages."""
    return section_in_each_language(WIKI / "en" / page, WIKI / "zh-CN" / page, heading)


def readme_section(heading: str) -> dict[str, str]:
    """``heading``'s section of the English README and of the Chinese README."""
    return section_in_each_language(ROOT / "README.md", ROOT / "README.zh-CN.md", heading)


def table_rows(body: str) -> list[list[str]]:
    """The cells of every table row in ``body``, divider rows left out (header rows stay)."""
    rows = []
    for line in body.splitlines():
        if not line.startswith("|") or set(line) <= set("|-: "):
            continue
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def first_table(body: str) -> str:
    """The first table in ``body``: its run of consecutive lines that start with ``|``."""
    lines = body.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("|"))
    end = next((i for i in range(start, len(lines)) if not lines[i].startswith("|")), len(lines))
    return "\n".join(lines[start:end])


def first_cell_codes(body: str) -> list[str]:
    """The code span that opens the first cell of each table row: the key of a reference table."""
    return FIRST_CELL_CODE.findall(body)


def code_spans(cell: str) -> list[str]:
    return CODE_SPAN.findall(cell)


def stated_numbers(body: str, pattern: str) -> tuple[int, ...]:
    """The numbers a page states in a sentence such as "There are 25 fields": ``pattern`` is a
    regular expression whose groups are the numbers."""
    match = re.search(pattern, body)
    assert match, f"no sentence matching {pattern!r}"
    return tuple(int(group) for group in match.groups())
