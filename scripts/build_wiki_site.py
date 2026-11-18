"""Build the wiki in docs/wiki into a static website for GitHub Pages.

Each language folder becomes its own Zensical site (`en/` and `zh-CN/`), and a small root
page sends the reader to one of them. The Markdown files stay written for reading on GitHub,
so their links are rewritten while the pages are copied:

- a link to another page of the same language stays relative (`Home.md` becomes `index.md`);
- a link to the other language points at the same page on the other site;
- a link to an image under docs/images copies the image into the site;
- a link to any other file in the repository points at that file on GitHub.

A link to a missing file, or to a file outside the repository, stops the build. The pages of
each language must match `_Sidebar.md`, which becomes the site navigation, and `_Footer.md`
is added to the end of every page, as GitHub Wiki would do.

    python -m pip install -e '.[docs]'
    python scripts/build_wiki_site.py             # writes build/wiki-site/public
    python -m http.server -d build/wiki-site/public 8000
"""

import argparse
import copy
import itertools
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

REPO = Path(__file__).resolve().parents[1]
GITHUB = "https://github.com/kirinhcl/diagri"
BRANCH = "main"
SITE_URL = "https://kirinhcl.github.io/diagri/"
DEFAULT_OUT = REPO / "build" / "wiki-site"
MARKER = ".wiki-site"
HOME = "Home.md"
NAVIGATION_FILES = frozenset({"_Sidebar.md", "_Footer.md"})


@dataclass(frozen=True)
class Language:
    folder: str  # folder under docs/wiki, and the path of the site under SITE_URL
    theme: str  # Zensical interface language
    name: str  # label in the language selector
    description: str
    toggles: tuple[str, str, str]  # colour scheme toggles: to light, to dark, to system


LANGUAGES = (
    Language(
        "en",
        "en",
        "English",
        "DiAGRI: an AI agent platform for plant growth research",
        ("Switch to light mode", "Switch to dark mode", "Follow the system setting"),
    ),
    Language(
        "zh-CN",
        "zh",
        "简体中文",
        "DiAGRI：面向植物生长研究的 AI Agent 平台",
        ("切换到浅色模式", "切换到深色模式", "跟随系统设置"),
    ),
)
FOLDERS = frozenset(language.folder for language in LANGUAGES)

# Only extensions whose output matches what GitHub shows for the same Markdown, so a page
# reads the same on GitHub and on the site. `toc` and `tables` are always on in Zensical.
# Headings get GitHub's anchors, which keep Chinese characters: `#记录一次测量` must work
# on both.
MARKDOWN_EXTENSIONS = {
    "toc": {
        "permalink": True,
        "slugify": {"object": "pymdownx.slugs.slugify", "kwds": {"case": "lower"}},
    },
    "admonition": {},
    "attr_list": {},
    "footnotes": {},
    "md_in_html": {},
    "pymdownx": {
        "betterem": {},
        "highlight": {"anchor_linenums": True, "pygments_lang_class": True},
        "inlinehilite": {},
        "magiclink": {},
        "superfences": {
            "custom_fences": [
                {
                    "name": "mermaid",
                    "class": "mermaid",
                    "format": "pymdownx.superfences.fence_code_format",
                }
            ]
        },
        "tasklist": {"custom_checkbox": True},
        "tilde": {"subscript": False},
    },
}

# The green of the operator console, so the wiki and the console look like one product.
EXTRA_CSS = """\
:root > * {
  --md-primary-fg-color: #23684d;
  --md-primary-fg-color--light: #2f8a64;
  --md-primary-fg-color--dark: #174d38;
  --md-accent-fg-color: #2f8a64;
}

[data-md-color-scheme="slate"] {
  --md-typeset-a-color: #7fcfa6;
  --md-accent-fg-color: #9fe0bd;
}
"""

# A backtick fence cannot carry a backtick in its info string: "```a``` text" is prose.
FENCE = re.compile(r"^\s*(`{3,}(?=[^`]*$)|~{3,})")
INLINE_CODE = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)")
CODE_PLACEHOLDER = re.compile("\x00(\\d+)\x00")
LINK_TARGET = re.compile(r"(?<=\]\()([^)\s]+)(?=[)\s])")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
# Links the build cannot rewrite. They work on GitHub but would break on the site, so they
# stop the build instead. Footnote definitions (`[^1]:`) are not links.
REFERENCE_DEFINITION = re.compile(r"^ {0,3}\[(?!\^)[^\]]+\]:\s*\S")
HTML_LINK = re.compile(
    r"<(?:a|img)\b[^>]*?\b(?:href|src)\s*=\s*[\"']?(?![A-Za-z][A-Za-z0-9+.-]*:|#)", re.I
)
SIDEBAR_HOME = re.compile(r"^\*\*\[(?P<title>[^\]]+)\]\((?P<file>[^)#\s]+)\)\*\*")
SIDEBAR_GROUP = re.compile(r"^\*\*(?P<title>[^*\[\]]+)\*\*\s*$")
SIDEBAR_ITEM = re.compile(r"^[-*] \[(?P<title>[^\]]+)\]\((?P<file>[^)#\s]+)\)\s*$")


class BrokenLinkError(ValueError):
    """A link points at a missing file or outside the repository."""


class SidebarError(ValueError):
    """`_Sidebar.md` and the pages of its language folder disagree."""


@dataclass(frozen=True)
class Rewritten:
    text: str
    images: frozenset[Path]


# Pages and links


def page_names(folder: Path) -> frozenset[str]:
    return frozenset(p.name for p in folder.glob("*.md") if p.name not in NAVIGATION_FILES)


def staged_name(name: str) -> str:
    return "index.md" if name == HOME else name


def page_url(name: str) -> str:
    """Where a page is served within its language site."""
    return "" if name == HOME else f"{name.removesuffix('.md')}/"


def rewrite_links(markdown: str, *, page: Path, repo: Path) -> Rewritten:
    """Rewrite the links of one page, leaving code blocks and inline code untouched."""
    page, repo = page.resolve(), repo.resolve()
    lines: list[str] = []
    images: set[Path] = set()
    fence: str | None = None
    for line in markdown.splitlines(keepends=True):
        if fence is not None:
            if _closes_fence(line, fence):
                fence = None
            lines.append(line)
        elif opening := FENCE.match(line):
            fence = opening[1]
            lines.append(line)
        else:
            text, found = _rewrite_line(line, page=page, repo=repo)
            lines.append(text)
            images.update(found)
    return Rewritten("".join(lines), frozenset(images))


def _closes_fence(line: str, fence: str) -> bool:
    stripped = line.strip()
    return len(stripped) >= len(fence) and set(stripped) == {fence[0]}


def _rewrite_line(line: str, *, page: Path, repo: Path) -> tuple[str, list[Path]]:
    spans: list[str] = []

    def hide(match: re.Match[str]) -> str:
        spans.append(match[0])
        return f"\x00{len(spans) - 1}\x00"

    images: list[Path] = []

    def replace(match: re.Match[str]) -> str:
        target, image = _rewrite_target(match[1], page=page, repo=repo)
        if image is not None:
            images.append(image)
        return target

    prose = INLINE_CODE.sub(hide, line)
    if REFERENCE_DEFINITION.match(prose) or HTML_LINK.search(prose):
        raise BrokenLinkError(
            f"{page}: write {line.strip()!r} as an inline link [text](target), "
            "which the site build can rewrite"
        )
    prose = LINK_TARGET.sub(replace, prose)
    return CODE_PLACEHOLDER.sub(lambda match: spans[int(match[1])], prose), images


def _rewrite_target(target: str, *, page: Path, repo: Path) -> tuple[str, Path | None]:
    if target.startswith("#") or SCHEME.match(target):
        return target, None
    parts = urlsplit(target)
    suffix = (f"?{parts.query}" if parts.query else "") + (
        f"#{parts.fragment}" if parts.fragment else ""
    )
    resolved = (page.parent / unquote(parts.path)).resolve()
    if not resolved.is_relative_to(repo):
        raise BrokenLinkError(f"{page}: {target} is outside the repository")
    if not resolved.exists():
        raise BrokenLinkError(f"{page}: {target} does not exist")

    wiki = repo / "docs" / "wiki"
    if resolved.suffix == ".md" and resolved.parent.parent == wiki:
        if resolved.parent == page.parent:
            return staged_name(resolved.name) + suffix, None
        if resolved.parent.name in FOLDERS:
            # Relative to the Markdown file: Zensical adds the `../` that a page served at
            # `Page/` needs.
            return f"../{resolved.parent.name}/{page_url(resolved.name)}{suffix}", None

    images = repo / "docs" / "images"
    if resolved.is_file() and resolved.is_relative_to(images):
        return f"images/{quote(resolved.relative_to(images).as_posix())}{suffix}", resolved

    kind = "tree" if resolved.is_dir() else "blob"
    path = quote(resolved.relative_to(repo).as_posix())
    return f"{GITHUB}/{kind}/{BRANCH}/{path}{suffix}", None


# Navigation


def build_nav(sidebar: str, pages: Collection[str]) -> list[dict]:
    """The site navigation, in the order and with the titles of `_Sidebar.md`."""
    entries: list[tuple[str | None, str, str]] = []
    group: str | None = None
    for line in sidebar.splitlines():
        if home := SIDEBAR_HOME.match(line):
            entries.append((None, home["title"], home["file"]))
        elif heading := SIDEBAR_GROUP.match(line):
            group = heading["title"].strip()
        elif item := SIDEBAR_ITEM.match(line):
            entries.append((group, item["title"], item["file"]))
    _check_sidebar([file for _, _, file in entries], pages)

    nav: list[dict] = []
    for name, items in itertools.groupby(entries, key=lambda entry: entry[0]):
        links = [{title: staged_name(file)} for _, title, file in items]
        if name is None:
            nav.extend(links)
        else:
            nav.append({name: links})
    return nav


def _check_sidebar(listed: list[str], pages: Collection[str]) -> None:
    problems = {
        "not in the sidebar": set(pages) - set(listed),
        "in the sidebar but not a page": set(listed) - set(pages),
        "in the sidebar twice": {name for name in listed if listed.count(name) > 1},
    }
    found = [f"{what}: {', '.join(sorted(names))}" for what, names in problems.items() if names]
    if found:
        raise SidebarError("; ".join(found))


# Configuration


def site_config(language: Language, nav: list[dict]) -> dict:
    to_light, to_dark, to_system = language.toggles
    colours = {"primary": "custom", "accent": "custom"}
    return {
        "project": {
            "site_name": "DiAGRI Wiki",
            "site_url": f"{SITE_URL}{language.folder}/",
            "site_description": language.description,
            "repo_url": GITHUB,
            "repo_name": "kirinhcl/diagri",
            "docs_dir": "docs",
            "site_dir": "site",
            "extra_css": ["stylesheets/extra.css"],
            "nav": nav,
            "theme": {
                "language": language.theme,
                # System fonts: Google Fonts is slow or blocked for many readers in China.
                "font": False,
                "icon": {"logo": "lucide/sprout"},
                "features": [
                    "content.code.copy",
                    "navigation.footer",
                    "navigation.sections",
                    "navigation.top",
                    "navigation.tracking",
                    "search.highlight",
                    "toc.follow",
                ],
                "palette": [
                    {
                        "media": "(prefers-color-scheme)",
                        **colours,
                        "toggle": {"icon": "lucide/sun-moon", "name": to_light},
                    },
                    {
                        "media": "(prefers-color-scheme: light)",
                        "scheme": "default",
                        **colours,
                        "toggle": {"icon": "lucide/sun", "name": to_dark},
                    },
                    {
                        "media": "(prefers-color-scheme: dark)",
                        "scheme": "slate",
                        **colours,
                        "toggle": {"icon": "lucide/moon", "name": to_system},
                    },
                ],
            },
            "extra": {
                "alternate": [
                    {"name": other.name, "link": f"../{other.folder}/", "lang": other.folder}
                    for other in LANGUAGES
                ]
            },
            "markdown_extensions": copy.deepcopy(MARKDOWN_EXTENSIONS),
        }
    }


def to_toml(config: dict) -> str:
    """TOML for a mapping of tables holding strings, booleans, lists and mappings."""
    lines: list[str] = []
    for table, values in config.items():
        lines.append(f"[{table}]")
        lines.extend(f"{_toml_key(key)} = {_toml_value(value)}" for key, value in values.items())
    return "\n".join(lines) + "\n"


def _toml_key(key: str) -> str:
    return json.dumps(key, ensure_ascii=False)


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        pairs = ", ".join(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in value.items())
        return "{ " + pairs + " }" if pairs else "{}"
    raise TypeError(f"cannot write {type(value).__name__} as TOML")


# Staging and building


def stage_language(language: Language, *, out: Path, repo: Path = REPO) -> Path:
    """Write one language as Zensical sources under `out`; return the configuration file."""
    source = repo / "docs" / "wiki" / language.folder
    docs = out / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    footer = (source / "_Footer.md").read_text(encoding="utf-8")
    pages = page_names(source)

    images: set[Path] = set()
    for name in sorted(pages):
        page = source / name
        text = page.read_text(encoding="utf-8").rstrip("\n") + "\n\n---\n\n" + footer
        result = rewrite_links(text, page=page, repo=repo)
        (docs / staged_name(name)).write_text(result.text, encoding="utf-8")
        images.update(result.images)

    image_root = (repo / "docs" / "images").resolve()
    for image in sorted(images):
        target = docs / "images" / image.relative_to(image_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(image, target)

    (docs / "stylesheets").mkdir(exist_ok=True)
    (docs / "stylesheets" / "extra.css").write_text(EXTRA_CSS, encoding="utf-8")

    nav = build_nav((source / "_Sidebar.md").read_text(encoding="utf-8"), pages)
    config = out / "zensical.toml"
    config.write_text(to_toml(site_config(language, nav)), encoding="utf-8")
    return config


def root_page() -> str:
    """The page at the site root: the reader's preferred language, English otherwise."""
    return """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DiAGRI Wiki</title>
<link rel="alternate" hreflang="en" href="en/">
<link rel="alternate" hreflang="zh-CN" href="zh-CN/">
<script>
  var preferred = (navigator.languages || [navigator.language || "en"]).find(function (code) {
    return /^(zh|en)\\b/i.test(code);
  }) || "en";
  location.replace(/^zh/i.test(preferred) ? "zh-CN/" : "en/");
</script>
<noscript><meta http-equiv="refresh" content="0; url=en/"></noscript>
</head>
<body>
<p><a href="en/">DiAGRI Wiki (English)</a> · <a href="zh-CN/">DiAGRI Wiki（简体中文）</a></p>
</body>
</html>
"""


def _prepare(out: Path) -> None:
    """Clear `out` for a new build, but only if it is empty or this script made it."""
    if out.exists():
        if not out.is_dir() or (any(out.iterdir()) and not (out / MARKER).is_file()):
            raise SystemExit(f"{out} is not a folder this script made; use another --out")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / MARKER).write_text("Made by scripts/build_wiki_site.py, which clears this folder.\n")


def _build(config: Path) -> None:
    command = [sys.executable, "-m", "zensical", "build", "--clean", "--strict", "-f", str(config)]
    if subprocess.run(command, cwd=config.parent).returncode != 0:
        raise SystemExit(f"zensical build failed for {config.parent.name}")


def _assemble(out: Path) -> Path:
    public = out / "public"
    for language in LANGUAGES:
        shutil.copytree(out / language.folder / "site", public / language.folder)
    (public / "index.html").write_text(root_page(), encoding="utf-8")
    shutil.copyfile(public / LANGUAGES[0].folder / "404.html", public / "404.html")
    return public


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the wiki website for GitHub Pages.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="build folder")
    parser.add_argument(
        "--stage-only", action="store_true", help="write the Zensical sources without building"
    )
    args = parser.parse_args(argv)
    out = args.out.resolve()

    _prepare(out)
    configs = [stage_language(language, out=out / language.folder) for language in LANGUAGES]
    if args.stage_only:
        return 0
    for config in configs:
        _build(config)
    print(f"Wiki site written to {_assemble(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
