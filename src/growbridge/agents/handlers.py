"""Binds each model role's tools to the real services (architecture doc §4, §5.2).

``build_role_tools`` returns, per model role, exactly the tools of ``tools.ROLE_TOOLS[role]``.
The ``search`` dependency is any object with ``search(query, limit) -> list[dict]`` (sync or async)
whose results carry ``title``, ``url`` and ``snippet`` text; ``None`` means "no search backend".
There is no handler for any tool in ``tools.CONTROL_TOOLS``.
"""

from __future__ import annotations

from growbridge.agents.handlers_auditor import build_auditor_tools
from growbridge.agents.handlers_common import Deps
from growbridge.agents.handlers_orchestrator import build_orchestrator_tools
from growbridge.agents.handlers_planner import build_planner_tools
from growbridge.agents.handlers_researcher import build_researcher_tools
from growbridge.agents.tools import CONTROL_TOOLS, ROLE_TOOLS, Tool

__all__ = ["Deps", "build_role_tools"]


def build_role_tools(deps: Deps) -> dict[str, list[Tool]]:
    tools = {
        "orchestrator": build_orchestrator_tools(deps),
        "planner": build_planner_tools(deps),
        "researcher": build_researcher_tools(deps),
        "auditor": build_auditor_tools(deps),
    }
    for role, built in tools.items():
        names = {tool.name for tool in built}
        if names != ROLE_TOOLS[role] or names & CONTROL_TOOLS:
            raise RuntimeError(f"handlers for {role!r} do not match the role's tool list")
    return tools
