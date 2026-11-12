"""The wiki under docs/wiki is bilingual: every page exists in both languages and links resolve."""

import re
from pathlib import Path

import pytest

WIKI = Path(__file__).resolve().parents[2] / "docs" / "wiki"
LANGUAGES = ("en", "zh-CN")
NAVIGATION = {"_Sidebar.md", "_Footer.md"}  # present in each language, not in the page table
FENCED_BLOCK = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
TABLE_FILE = re.compile(r"\| `([A-Za-z-]+\.md)` \|")
EXTERNAL = ("http://", "https://", "mailto:")


def page_names(language: str) -> set[str]:
    return {path.name for path in (WIKI / language).glob("*.md")}


def prose(path: Path) -> str:
    """The page without code, so that link examples inside code are not checked."""
    return INLINE_CODE.sub("", FENCED_BLOCK.sub("", path.read_text(encoding="utf-8")))


def wiki_files() -> list[Path]:
    return sorted([WIKI / "README.md", *WIKI.glob("*/*.md")])


def content_pages() -> list[Path]:
    return [p for p in wiki_files() if p.parent != WIKI and p.name not in NAVIGATION]


def relative_id(path: Path) -> str:
    return str(path.relative_to(WIKI))


def test_every_page_exists_in_both_languages():
    assert page_names("en") == page_names("zh-CN")


def test_the_page_table_lists_exactly_the_pages_that_exist():
    listed = set(TABLE_FILE.findall((WIKI / "README.md").read_text(encoding="utf-8")))

    assert listed | NAVIGATION == page_names("en")


@pytest.mark.parametrize("page", wiki_files(), ids=relative_id)
def test_relative_links_point_at_existing_files(page: Path):
    targets = [t for t in LINK.findall(prose(page)) if not t.startswith(EXTERNAL)]
    paths = [t.split("#", 1)[0] for t in targets if not t.startswith("#")]

    missing = [t for t in paths if not (page.parent / t).exists()]

    assert missing == []


@pytest.mark.parametrize("page", content_pages(), ids=relative_id)
def test_each_page_links_to_its_translation(page: Path):
    other = next(lang for lang in LANGUAGES if lang != page.parent.name)

    assert f"](../{other}/{page.name})" in prose(page)
