from growbridge.agents.tools import build_toolset

EXPECTED = {
    "lookup_crop_conditions",
    "search_and_verify_sources",
    "submit_compute_job",
    "get_compute_job",
    "fetch_compute_artifacts",
}


def test_every_web_tool_is_external(env):
    for tools in env.tools().values():
        for tool in tools:
            if tool.reads_web:
                assert tool.external, tool.name


def test_external_tools_are_exactly_the_reviewed_list(env):
    names = {t.name for tools in env.tools().values() for t in tools if t.external}
    assert names == EXPECTED


def test_toolset_reports_external_by_name(env):
    toolset = build_toolset("planner", env.tools()["planner"])
    assert toolset.external("search_and_verify_sources")
    assert not toolset.external("validate_run_sheet")
    assert not toolset.external("no_such_tool")
