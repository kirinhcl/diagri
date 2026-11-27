"""Which data directory a replay starts from, and when it reads the configuration."""

import pytest

from growbridge.agents.trace import Trace, TraceFormatError
from growbridge.replay_runtime import choose_source, recorded_settings


def _trace(pre_run_copy, **run):
    return Trace(run={"pre_run_copy": pre_run_copy, **run})


def _unread():
    raise AssertionError("the configuration must not be read here")


def test_source_order(tmp_path, settings):
    trace_path = tmp_path / "t.jsonl"
    pre = tmp_path / "t.pre"
    pre.mkdir()
    option = tmp_path / "chosen"

    given = choose_source(trace_path, _trace("t.pre"), option, _unread)
    assert (given.path, given.kind, given.reliable) == (option, "option", False)

    own = choose_source(trace_path, _trace("t.pre"), None, _unread)
    assert (own.path, own.kind, own.reliable) == (pre, "pre_run_copy", True)

    configured = choose_source(trace_path, _trace(None), None, lambda: settings)
    assert (configured.path, configured.kind, configured.reliable) == (
        settings.data_dir,
        "config",
        False,
    )


def test_a_named_but_missing_pre_run_copy_falls_back_to_the_config(tmp_path, settings):
    source = choose_source(tmp_path / "t.jsonl", _trace("t.pre"), None, lambda: settings)

    assert source.kind == "config" and not source.reliable


def test_recorded_settings_get_a_fresh_token(settings):
    recorded = settings.model_dump(mode="json", exclude={"token"})

    first = recorded_settings(_trace(None, settings=recorded))
    second = recorded_settings(_trace(None, settings=recorded))

    assert first is not None and second is not None
    assert first.model_dump(exclude={"token"}) == settings.model_dump(exclude={"token"})
    assert len({first.token, second.token, settings.token}) == 3
    assert recorded_settings(_trace(None)) is None  # an older trace: the caller falls back


def test_recorded_settings_that_no_longer_validate_cannot_be_replayed(settings):
    recorded = {**settings.model_dump(mode="json", exclude={"token"}), "port": 1}

    with pytest.raises(TraceFormatError, match="port"):
        recorded_settings(_trace(None, settings=recorded))
