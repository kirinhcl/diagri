"""Which data directory a replay starts from."""

from growbridge.agents.trace import Trace
from growbridge.replay_runtime import choose_source


def _trace(pre_run_copy):
    return Trace(run={"pre_run_copy": pre_run_copy})


def test_source_order(tmp_path, settings):
    trace_path = tmp_path / "t.jsonl"
    pre = tmp_path / "t.pre"
    pre.mkdir()
    option = tmp_path / "chosen"

    given = choose_source(trace_path, _trace("t.pre"), option, settings)
    assert (given.path, given.kind, given.reliable) == (option, "option", False)

    own = choose_source(trace_path, _trace("t.pre"), None, settings)
    assert (own.path, own.kind, own.reliable) == (pre, "pre_run_copy", True)

    configured = choose_source(trace_path, _trace(None), None, settings)
    assert (configured.path, configured.kind, configured.reliable) == (
        settings.data_dir,
        "config",
        False,
    )


def test_a_named_but_missing_pre_run_copy_falls_back_to_the_config(tmp_path, settings):
    source = choose_source(tmp_path / "t.jsonl", _trace("t.pre"), None, settings)

    assert source.kind == "config" and not source.reliable
