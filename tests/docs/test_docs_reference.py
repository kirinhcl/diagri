"""The reference pages of the wiki, and the README's tool table, list what the code has.

Each test reads a table from the English page and from its Chinese twin and compares it with the
registry it documents: the codes ``Denied`` is raised with, the CLI parser, the configuration
models, the MCP server and the model role tool sets. A failure names what is missing on the page
and what the page lists that the code does not have.
"""

from __future__ import annotations

import argparse
import ast
import re
import tomllib

import pytest
from wiki_pages import (
    LANGUAGES,
    ROOT,
    code_spans,
    first_cell_codes,
    first_table,
    readme_section,
    stated_numbers,
    table_rows,
    wiki_section,
)

from growbridge.agents.tools import ROLE_TOOLS
from growbridge.cli import build_parser
from growbridge.config import RoleModel, Settings
from growbridge.denial_codes import DENIAL_CODES
from growbridge.mcp_server import create_mcp
from growbridge.ports import Denied

SOURCE = ROOT / "src" / "growbridge"
YES = {"yes", "有"}


def differences(documented: set, actual: set) -> dict[str, list]:
    """What the page misses and what it lists that the code lacks: empty when they agree."""
    missing = sorted(actual - documented)
    extra = sorted(documented - actual)
    return {k: v for k, v in (("missing from page", missing), ("not in code", extra)) if v}


# --- denial codes --------------------------------------------------------------------------------


def called_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def raised_denial_codes() -> set[str]:
    """Every literal code ``Denied`` is constructed with in ``src/``, plus every coarse code a
    registered denial reason refines."""
    codes = {code.of for code in DENIAL_CODES.values() if code.of}
    for path in SOURCE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and called_name(node.func) == "Denied"):
                continue
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                codes.add(first.value)
    return codes


def docstring_codes() -> set[str]:
    paragraph = next(p for p in (Denied.__doc__ or "").split("\n\n") if "Codes used" in p)
    return set(re.findall(r"``([a-z_]+)``", paragraph))


def test_the_denied_docstring_names_exactly_the_codes_raised():
    assert differences(docstring_codes(), raised_denial_codes()) == {}


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_denial_code_table_lists_exactly_the_codes_raised(language):
    body = wiki_section("Denial-Codes-and-Events.md", "Denial codes")[language]
    table = first_cell_codes(first_table(body))

    assert len(table) == len(set(table)), "a code is listed twice"
    assert differences(set(table), raised_denial_codes()) == {}


@pytest.mark.parametrize(
    ("language", "pattern"),
    [
        ("en", r"names (\d+) codes, and the code raises exactly those (\d+)"),
        ("zh-CN", r"列了 (\d+) 个拒绝码，代码里抛出的也正好是这 (\d+) 个"),
    ],
)
def test_the_denial_code_count_is_stated_correctly(language, pattern):
    body = wiki_section("Denial-Codes-and-Events.md", "Denial codes")[language]
    count = len(raised_denial_codes())

    assert stated_numbers(body, pattern) == (count, count)


# --- CLI -----------------------------------------------------------------------------------------
# argparse has no public API to list a parser's arguments or subcommands; ``_actions`` and the
# action classes below have been stable since Python 3.2. If an upgrade breaks them, these tests
# fail at collection, not silently.


def subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def arguments(parser: argparse.ArgumentParser) -> set[str]:
    """The long options and the positional names of one parser, help left out."""
    found: set[str] = set()
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction | argparse._SubParsersAction):
            continue
        found |= {s for s in action.option_strings if s.startswith("--")}
        if not action.option_strings:
            found.add(action.dest)
    return found


def cli_commands() -> dict[str, set[str]]:
    """Each command as the wiki writes it (``init``, ``operator add``) and its arguments."""
    commands: dict[str, set[str]] = {}
    for name, parser in subparsers(build_parser()).items():
        nested = subparsers(parser)
        leaves = {f"{name} {sub}": p for sub, p in nested.items()} if nested else {name: parser}
        commands |= {command: arguments(leaf) for command, leaf in leaves.items()}
    return commands


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_subcommand_table_lists_every_command_with_its_arguments(language):
    body = wiki_section("CLI-Reference.md", "Subcommands")[language]
    documented = {
        code_spans(row[0])[0]: {span.split()[0] for span in code_spans(row[1])}
        for row in table_rows(body)
        if code_spans(row[0])
    }
    actual = cli_commands()

    assert differences(set(documented), set(actual)) == {}
    wrong = {c: differences(documented[c], actual[c]) for c in actual if c in documented}
    assert {c: d for c, d in wrong.items() if d} == {}


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_global_option_table_lists_every_global_option(language):
    body = wiki_section("CLI-Reference.md", "Global options")[language]
    documented = {span for row in table_rows(body) for span in code_spans(row[0])}
    parser = build_parser()
    actual = {s for action in parser._actions for s in action.option_strings}

    assert differences(documented, actual) == {}


@pytest.mark.parametrize(
    ("language", "pattern"),
    [("en", r"There are (\d+) subcommands"), ("zh-CN", r"共 (\d+) 个子命令")],
)
def test_the_subcommand_count_is_stated_correctly(language, pattern):
    body = wiki_section("CLI-Reference.md", "Subcommands")[language]

    assert stated_numbers(body, pattern) == (len(subparsers(build_parser())),)


# --- configuration -------------------------------------------------------------------------------

FIELD_COUNT = {"en": r"There are (\d+) fields", "zh-CN": r"共 (\d+) 个字段"}


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize(
    ("heading", "model"),
    [("`Settings` fields", Settings), ("`RoleModel` fields", RoleModel)],
    ids=["Settings", "RoleModel"],
)
def test_the_field_table_lists_every_configuration_field(language, heading, model):
    body = wiki_section("Configuration-Reference.md", heading)[language]
    table = first_cell_codes(body)

    assert len(table) == len(set(table)), "a field is listed twice"
    assert differences(set(table), set(model.model_fields)) == {}
    assert stated_numbers(body, FIELD_COUNT[language]) == (len(model.model_fields),)


# --- MCP tools -----------------------------------------------------------------------------------


async def mcp_tools(auto_research: bool) -> set[str]:
    settings = Settings(device="SIMULATED", token="t" * 32, data_dir="/nonexistent", port=8766)
    settings = settings.model_copy(update={"auto_research": auto_research})
    return {tool.name for tool in await create_mcp(settings).list_tools()}


@pytest.mark.parametrize("language", LANGUAGES)
async def test_the_wiki_mcp_table_lists_the_tools_of_each_mode(language):
    body = wiki_section("API-Reference.md", "MCP tools")[language]
    rows = [row for row in table_rows(body) if code_spans(row[0])]
    bridge_only = {code_spans(row[0])[0] for row in rows if row[1] in YES}
    diagri = {code_spans(row[0])[0] for row in rows if row[2] in YES}

    assert differences(bridge_only, await mcp_tools(auto_research=False)) == {}
    assert differences(diagri, await mcp_tools(auto_research=True)) == {}


@pytest.mark.parametrize(
    ("language", "pattern"),
    [
        ("en", r"Bridge-only mode has (\d+) tools\. DiAGRI mode has the (\d+) read tools"),
        ("zh-CN", r"仅桥接模式有 (\d+) 个工具，DiAGRI 模式只有 (\d+) 个读取工具"),
    ],
)
async def test_the_mcp_tool_counts_are_stated_correctly(language, pattern):
    body = wiki_section("API-Reference.md", "MCP tools")[language]
    expected = (len(await mcp_tools(False)), len(await mcp_tools(True)))

    assert stated_numbers(body, pattern) == expected


@pytest.mark.parametrize("language", LANGUAGES)
async def test_the_readme_tool_table_lists_the_bridge_only_tools(language):
    body = readme_section("Dashboard and MCP")[language]

    assert differences(set(first_cell_codes(body)), await mcp_tools(auto_research=False)) == {}


# --- model role tools ----------------------------------------------------------------------------

ROLE_COUNT = {
    "en": (
        r"The orchestrator has (\d+) tools, the planner (\d+), the researcher (\d+) "
        r"and the auditor (\d+)"
    ),
    "zh-CN": (
        r"编排 Agent 有 (\d+) 个工具，计划 Agent 有 (\d+) 个，研究 Agent 有 (\d+) 个，"
        r"监察 Agent 有 (\d+) 个"
    ),
}


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_model_role_table_lists_every_tool_of_every_role(language):
    body = wiki_section("API-Reference.md", "Model role tools")[language]
    documented = {
        (row[0], code_spans(row[1])[0])
        for row in table_rows(body)
        if len(row) > 1 and code_spans(row[1]) and row[0] in ROLE_TOOLS
    }
    actual = {(role, tool) for role, tools in ROLE_TOOLS.items() for tool in tools}

    assert differences(documented, actual) == {}


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_model_role_tool_counts_are_stated_correctly(language):
    body = wiki_section("API-Reference.md", "Model role tools")[language]
    roles = ("orchestrator", "planner", "researcher", "auditor")

    assert stated_numbers(body, ROLE_COUNT[language]) == tuple(len(ROLE_TOOLS[r]) for r in roles)


# --- citation ------------------------------------------------------------------------------------


def test_the_citation_names_the_package_version():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    cited = re.search(r'^version: "([^"]+)"$', citation, re.MULTILINE)

    assert cited is not None, "CITATION.cff has no quoted version line"
    assert cited.group(1) == project["version"]
