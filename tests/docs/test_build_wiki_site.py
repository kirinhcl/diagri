"""The wiki website: links that work when the wiki is read on GitHub keep working on the site."""

import importlib.util
import re
import tomllib
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_wiki_site.py"
BLOB = "https://github.com/kirinhcl/diagri/blob/main/"
TREE = "https://github.com/kirinhcl/diagri/tree/main/"
SIDEBAR = """**[Home](Home.md)** · [简体中文](../zh-CN/Home.md)

**Start**

- [Glossary](Glossary.md)
- [A page](Page.md)
"""
PAGES = {"Home.md", "Glossary.md", "Page.md"}


def _load_script():
    spec = importlib.util.spec_from_file_location("build_wiki_site", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


site = _load_script()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    files = {
        "src/pkg/mod.py": "x = 1\n",
        "docs/arch.md": "# Architecture\n",
        "docs/images/round/shot.jpg": "not really a jpeg",
        "docs/wiki/README.md": "# Wiki\n",
    }
    for language in ("en", "zh-CN"):
        for name in PAGES:
            files[f"docs/wiki/{language}/{name}"] = f"# {name}\n"
        files[f"docs/wiki/{language}/_Sidebar.md"] = SIDEBAR
        files[f"docs/wiki/{language}/_Footer.md"] = "Checked. See [Glossary](Glossary.md).\n"
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def rewrite(repo: Path, markdown: str, page: str = "en/Page.md"):
    return site.rewrite_links(markdown, page=repo / "docs" / "wiki" / page, repo=repo)


# Links


def test_links_between_pages_of_one_language_stay_relative(repo):
    result = rewrite(repo, "[G](Glossary.md#term) and [back](Home.md)")

    assert result.text == "[G](Glossary.md#term) and [back](index.md)"


def test_links_to_the_other_language_point_at_the_other_site(repo):
    # Zensical reads a plain relative link as relative to the Markdown file and adds the
    # `../` that a page served at `Page/` needs, so every page writes the same link.
    from_page = rewrite(repo, "[中文](../zh-CN/Page.md) [首页](../zh-CN/Home.md#top)")
    from_home = rewrite(repo, "[术语](../zh-CN/Glossary.md)", page="en/Home.md")

    assert from_page.text == "[中文](../zh-CN/Page/) [首页](../zh-CN/#top)"
    assert from_home.text == "[术语](../zh-CN/Glossary/)"


def test_links_to_repository_files_point_at_github(repo):
    result = rewrite(
        repo,
        "[f](../../../src/pkg/mod.py#L1) [d](../../../src/pkg) "
        "[r](../README.md) [a](../../arch.md)",
    )

    assert result.text == (
        f"[f]({BLOB}src/pkg/mod.py#L1) [d]({TREE}src/pkg) "
        f"[r]({BLOB}docs/wiki/README.md) [a]({BLOB}docs/arch.md)"
    )


def test_images_are_copied_into_the_site(repo):
    result = rewrite(repo, "![shot](../../images/round/shot.jpg)")

    assert result.text == "![shot](images/round/shot.jpg)"
    assert result.images == frozenset({repo / "docs" / "images" / "round" / "shot.jpg"})


def test_external_and_anchor_links_are_left_alone(repo):
    text = "[w](https://example.org/a) [m](mailto:someone@example.org) [s](#section)"

    assert rewrite(repo, text).text == text


def test_code_is_not_rewritten_but_code_inside_link_text_is(repo):
    text = (
        "```text\n[x](../../../src/pkg/mod.py)\n```\n"
        "Use `[x](Home.md)` literally. See [`mod.py`](../../../src/pkg/mod.py).\n"
    )

    result = rewrite(repo, text)

    assert result.text == (
        "```text\n[x](../../../src/pkg/mod.py)\n```\n"
        f"Use `[x](Home.md)` literally. See [`mod.py`]({BLOB}src/pkg/mod.py).\n"
    )


def test_a_backtick_line_that_is_not_a_fence_does_not_hide_later_links(repo):
    # A backtick fence's info string cannot contain a backtick, so this line is prose.
    text = "```python x``` [a](Home.md)\n[b](../../../src/pkg/mod.py)\n"

    result = rewrite(repo, text)

    assert result.text == f"```python x``` [a](index.md)\n[b]({BLOB}src/pkg/mod.py)\n"


def test_a_query_string_is_kept_after_the_github_path(repo):
    result = rewrite(repo, "[m](../../../src/pkg/mod.py?plain=1#L1)")

    assert result.text == f"[m]({BLOB}src/pkg/mod.py?plain=1#L1)"


def test_generated_urls_are_percent_encoded(repo):
    spaced = repo / "src" / "pkg" / "a b.py"
    spaced.write_text("x = 1\n", encoding="utf-8")

    result = rewrite(repo, "[s](../../../src/pkg/a%20b.py)")

    assert result.text == f"[s]({BLOB}src/pkg/a%20b.py)"


def test_a_link_to_the_images_folder_itself_points_at_github(repo):
    result = rewrite(repo, "[all](../../images/round)")

    assert result.text == f"[all]({TREE}docs/images/round)"
    assert result.images == frozenset()


@pytest.mark.parametrize(
    "markdown",
    [
        "[ref]: ../../../src/pkg/mod.py\n",
        '<img src="../../images/round/shot.jpg" alt="shot">\n',
        '<a href="Glossary.md">Glossary</a>\n',
    ],
    ids=["reference definition", "html image", "html link"],
)
def test_links_the_build_cannot_rewrite_stop_it(repo, markdown):
    with pytest.raises(site.BrokenLinkError, match="inline"):
        rewrite(repo, markdown)


def test_a_link_to_a_missing_file_stops_the_build(repo):
    with pytest.raises(site.BrokenLinkError, match="Missing.md"):
        rewrite(repo, "[x](Missing.md)")


def test_a_link_that_leaves_the_repository_stops_the_build(repo):
    (repo.parent / "outside.md").write_text("# Outside\n", encoding="utf-8")

    with pytest.raises(site.BrokenLinkError, match="outside.md"):
        rewrite(repo, "[x](../../../../outside.md)")


# Navigation


def test_navigation_follows_the_sidebar():
    nav = site.build_nav(SIDEBAR, PAGES)

    assert nav == [
        {"Home": "index.md"},
        {"Start": [{"Glossary": "Glossary.md"}, {"A page": "Page.md"}]},
    ]


def test_navigation_rejects_a_page_missing_from_the_sidebar():
    with pytest.raises(site.SidebarError, match="Extra.md"):
        site.build_nav(SIDEBAR, PAGES | {"Extra.md"})


def test_navigation_rejects_a_sidebar_entry_without_a_page():
    with pytest.raises(site.SidebarError, match="Page.md"):
        site.build_nav(SIDEBAR, PAGES - {"Page.md"})


@pytest.mark.parametrize("language", ["en", "zh-CN"])
def test_the_real_sidebar_lists_every_page_once(language: str):
    folder = ROOT / "docs" / "wiki" / language
    pages = site.page_names(folder)

    nav = site.build_nav((folder / "_Sidebar.md").read_text(encoding="utf-8"), pages)

    listed = [target for entry in nav for target in _targets(entry)]
    assert sorted(listed) == sorted(site.staged_name(name) for name in pages)


def _targets(entry: dict) -> list[str]:
    (value,) = entry.values()
    return [value] if isinstance(value, str) else [t for item in value for t in _targets(item)]


# Configuration


def test_the_configuration_is_valid_toml():
    config = site.site_config(site.LANGUAGES[1], site.build_nav(SIDEBAR, PAGES))

    assert tomllib.loads(site.to_toml(config)) == config


def test_strings_with_quotes_backslashes_and_newlines_survive_toml():
    config = {"project": {"name": 'a "b" \\ c\nd 中文', "flag": False, "empty": {}}}

    assert tomllib.loads(site.to_toml(config)) == config


def test_toml_refuses_values_it_cannot_write():
    with pytest.raises(TypeError, match="float"):
        site.to_toml({"project": {"ratio": 0.5}})


def test_each_site_offers_both_languages():
    for language in site.LANGUAGES:
        project = site.site_config(language, [])["project"]

        links = [alternate["link"] for alternate in project["extra"]["alternate"]]
        assert links == ["../en/", "../zh-CN/"]
        assert project["site_url"].endswith(f"/{language.folder}/")


# Staging


def test_staging_writes_pages_with_the_footer_images_and_configuration(repo, tmp_path):
    page = repo / "docs" / "wiki" / "en" / "Page.md"
    page.write_text("# Page\n\n![shot](../../images/round/shot.jpg)\n", encoding="utf-8")
    out = tmp_path / "out"

    site.stage_language(site.LANGUAGES[0], repo=repo, out=out)

    docs = out / "docs"
    assert sorted(p.name for p in docs.glob("*.md")) == ["Glossary.md", "Page.md", "index.md"]
    staged = (docs / "Page.md").read_text(encoding="utf-8")
    assert staged.endswith("Checked. See [Glossary](Glossary.md).\n")
    assert (docs / "images" / "round" / "shot.jpg").is_file()
    config = tomllib.loads((out / "zensical.toml").read_text(encoding="utf-8"))
    assert config["project"]["theme"]["language"] == "en"


@pytest.mark.parametrize("language", site.LANGUAGES, ids=lambda language: language.folder)
def test_no_staged_link_leaves_the_site(language, tmp_path):
    site.stage_language(language, repo=ROOT, out=tmp_path)

    other = next(lang.folder for lang in site.LANGUAGES if lang != language)
    allowed = re.compile(rf"^\.\./{re.escape(other)}/")
    escaping = [
        target
        for path in (tmp_path / "docs").glob("*.md")
        for target in re.findall(r"\]\((\.\./[^)\s]*)\)", path.read_text(encoding="utf-8"))
        if not allowed.match(target)
    ]
    assert escaping == []


def test_the_root_page_redirects_without_script_only_as_a_fallback():
    page = site.root_page()

    # A refresh outside <noscript> could race the script's choice of language.
    assert re.search(r'<noscript><meta http-equiv="refresh" content="0; url=en/"></noscript>', page)
    assert page.count('http-equiv="refresh"') == 1
    assert 'href="en/"' in page and 'href="zh-CN/"' in page


def test_the_build_refuses_to_clear_a_folder_it_did_not_create(tmp_path):
    (tmp_path / "keep.txt").write_text("mine", encoding="utf-8")

    with pytest.raises(SystemExit):
        site.main(["--out", str(tmp_path), "--stage-only"])

    assert (tmp_path / "keep.txt").is_file()


def test_the_build_refuses_a_file_as_its_folder(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("mine", encoding="utf-8")

    with pytest.raises(SystemExit):
        site.main(["--out", str(target), "--stage-only"])

    assert target.read_text(encoding="utf-8") == "mine"


def test_the_build_reuses_an_empty_folder_and_clears_its_own(tmp_path):
    assert site.main(["--out", str(tmp_path), "--stage-only"]) == 0
    stale = tmp_path / "en" / "docs" / "Removed-Page.md"
    stale.write_text("# Gone\n", encoding="utf-8")

    assert site.main(["--out", str(tmp_path), "--stage-only"]) == 0

    assert not stale.exists()
    assert (tmp_path / "en" / "docs" / "index.md").is_file()


def test_the_whole_site_builds(tmp_path):
    pytest.importorskip("zensical")
    out = tmp_path / "wiki-site"

    assert site.main(["--out", str(out)]) == 0

    public = out / "public"
    for page in ("index.html", "404.html", "en/index.html", "zh-CN/index.html"):
        assert (public / page).is_file(), page
    assert (public / "en" / "Glossary" / "index.html").is_file()
    assert (public / "zh-CN" / "images").is_dir()
    assert _links_that_miss(public, base="/diagri/") == []


def _links_that_miss(public: Path, *, base: str) -> list[str]:
    """Local links that leave the site or find no file when it is served under `base`.

    GitHub Pages serves the site under /diagri/, so a link with one `../` too many leaves the
    site there, while a local server at / would quietly drop the extra step.
    """
    missing = []
    for html in public.rglob("*.html"):
        page = base + html.relative_to(public).as_posix()
        for ref in re.findall(r'(?:href|src)="([^"]+)"', html.read_text(encoding="utf-8")):
            if urlsplit(ref).scheme or ref.startswith(("#", "//")):
                continue
            path = urlsplit(urljoin(page, ref)).path
            file = public / unquote(path.removeprefix(base))
            if path.endswith("/"):
                file = file / "index.html"
            if not path.startswith(base) or not file.exists():
                missing.append(f"{page} -> {ref}")
    return missing
