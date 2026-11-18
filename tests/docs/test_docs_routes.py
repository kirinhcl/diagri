"""The route tables of the API reference list every route the bridge app and the workbench serve,
in both languages, with the counts the pages state."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from starlette.routing import Mount
from wiki_pages import LANGUAGES, code_spans, stated_numbers, table_rows, wiki_section

from growbridge.api import create_app
from growbridge.config import Settings

# The workbench test bench builds every optional service the runtime passes.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workbench"))
from workbench_support import Bench, default_compute  # noqa: E402

METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
MOUNT_WORDS = {"mount", "挂载"}
Route = tuple[str, str]  # (method or "mount", path)


def served(routes) -> set[Route]:
    """Every (method, path) in ``routes``, through included routers; a static mount is
    ``("mount", path)``."""
    found: set[Route] = set()
    for route in routes:
        if isinstance(route, Mount):
            found.add(("mount", route.path))
        elif (included := getattr(route, "original_router", None)) is not None:
            found |= served(included.routes)
        else:
            found |= {(method, route.path) for method in getattr(route, "methods", ())}
    return found


def documented(body: str) -> set[Route]:
    """Rows written as ``| `POST` | `/wb/login` |``, as ``| `GET /wb/greenhouses` |`` or, for a
    static mount, as ``| mount | `/assets` |`` (``挂载`` in Chinese)."""
    found: set[Route] = set()
    for row in table_rows(body):
        first = code_spans(row[0]) or (["mount"] if row[0] in MOUNT_WORDS else [])
        if not first:
            continue
        words = first[0].split()
        if len(words) == 2 and words[0] in METHODS:
            found.add((words[0], words[1]))
        elif words[0] in METHODS | {"mount"} and len(row) > 1 and code_spans(row[1]):
            found.add((words[0], code_spans(row[1])[0]))
    return found


def differences(on_page: set[Route], actual: set[Route]) -> dict[str, list[Route]]:
    missing = sorted(actual - on_page)
    extra = sorted(on_page - actual)
    return {k: v for k, v in (("missing from page", missing), ("not in code", extra)) if v}


@pytest.fixture(scope="module")
def workbench_routes(tmp_path_factory) -> dict[str, set[Route]]:
    """The routes with every optional service mounted, without and with ``multi_user``."""
    single = Bench(tmp_path_factory.mktemp("single"), compute_factory=default_compute)
    multi = Bench.full(tmp_path_factory.mktemp("multi"))
    try:
        return {"single": single.wb_routes(), "multi": multi.wb_routes()}
    finally:
        single.db.close()
        multi.db.close()


def bridge_routes() -> set[Route]:
    settings = Settings(device="SIMULATED", token="t" * 32, data_dir="/nonexistent")
    return served(create_app(settings, bridge=object()).routes)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_bridge_route_table_lists_every_bridge_route(language):
    body = wiki_section("API-Reference.md", "Bridge HTTP API")[language]

    assert differences(documented(body), bridge_routes()) == {}


@pytest.mark.parametrize(
    ("language", "pattern"),
    [
        ("en", r"There are (\d+) routes and one static mount"),
        ("zh-CN", r"共 (\d+) 个路由和一个静态挂载"),
    ],
)
def test_the_bridge_route_count_is_stated_correctly(language, pattern):
    body = wiki_section("API-Reference.md", "Bridge HTTP API")[language]
    routes = {route for route in bridge_routes() if route[0] != "mount"}

    assert stated_numbers(body, pattern) == (len(routes),)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_workbench_route_tables_list_every_workbench_route(language, workbench_routes):
    body = wiki_section("API-Reference.md", "Workbench routes")[language]
    multi_user = wiki_section("API-Reference.md", "Multi-user routes")[language]
    single, multi = workbench_routes["single"], workbench_routes["multi"]

    assert differences(documented(body), single) == {}
    assert differences(documented(multi_user), multi - single) == {}


@pytest.mark.parametrize(
    ("language", "pattern"),
    [
        ("en", r"There are (\d+) routes, and (\d+) more with `multi_user`"),
        ("zh-CN", r"共 (\d+) 个路由；打开 `multi_user` 时再多 (\d+) 个"),
    ],
)
def test_the_workbench_route_counts_are_stated_correctly(language, pattern, workbench_routes):
    body = wiki_section("API-Reference.md", "Workbench routes")[language]
    single, multi = workbench_routes["single"], workbench_routes["multi"]

    assert stated_numbers(body, pattern) == (len(single), len(multi - single))
