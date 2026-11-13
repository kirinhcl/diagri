import tomllib
from fnmatch import fnmatchcase
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "growbridge" / "web"


def _matches(path: str, pattern: str) -> bool:
    # setuptools package-data semantics without "**": same depth, each part fnmatch-ed
    parts, globs = path.split("/"), pattern.split("/")
    return len(parts) == len(globs) and all(map(fnmatchcase, parts, globs))


def test_every_web_asset_is_in_the_package_data():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    patterns = config["tool"]["setuptools"]["package-data"]["growbridge"]
    files = [
        "web/" + path.relative_to(WEB).as_posix()
        for path in WEB.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]
    unmatched = [f for f in files if not any(_matches(f, p) for p in patterns)]
    assert unmatched == []


def test_both_pages_share_the_design_tokens():
    tokens_css = (WEB / "tokens.css").read_text()
    style_css = (WEB / "style.css").read_text()
    index_html = (WEB / "index.html").read_text()
    assert "--ink: #172e28" in tokens_css and "--ink:" not in style_css
    assert index_html.index("/assets/tokens.css") < index_html.index("/assets/style.css")


def test_the_token_move_keeps_both_stylesheets_well_formed():
    tokens_css = (WEB / "tokens.css").read_text().strip()
    style_css = (WEB / "style.css").read_text().strip()
    assert tokens_css.startswith(":root {") and tokens_css.endswith("}")
    assert not style_css.startswith("}")
    assert style_css.startswith("* {")
    assert tokens_css.count("{") == tokens_css.count("}")
    assert style_css.count("{") == style_css.count("}")
