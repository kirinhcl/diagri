"""`growbridge serve` starts the compute service only when it is completely configured."""

import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from growbridge import cli
from growbridge.config import Settings

ENV = {
    "FIRECREST_URL": "https://api.example.test/v1",
    "FIRECREST_TOKEN_URL": "https://auth.example.test/token",
    "FIRECREST_CLIENT_ID": "robot-account",
    "FIRECREST_CLIENT_SECRET": "s3cr3t-client-secret",
    "FIRECREST_SYSTEM": "cpu",
    "FIRECREST_ACCOUNT": "project_2001234",
    "FIRECREST_WORKDIR": "/scratch/project_2001234/diagri",
}
TEMPLATE = {
    "id": "segment",
    "version": 1,
    "script": "#!/bin/bash\n#SBATCH --time=00:10:00\necho hi\n",
    "parameters": {"epochs": {"kind": "int", "minimum": 1, "maximum": 100}},
    "max_cpu_hours": 10,
    "max_storage_gb": 5,
}


class StopHere(ValueError):
    """Raised by the fake runtime so that ``serve`` ends right after the wiring."""


@pytest.fixture
def served(monkeypatch, tmp_path):
    """Run ``_serve_auto_research`` up to the workbench; record how the runtime was built."""
    seen = {}
    runtime = SimpleNamespace(
        compute=SimpleNamespace(input_guard=None),
        workflow=None,
        control=None,
        archive=SimpleNamespace(root=tmp_path),
        tasks=None,
        clock=None,
        holdout=None,
    )

    def fake_build(settings, *args, **options):
        seen.update(options)
        if "compute_backend" not in options:
            runtime.compute = None
        return runtime

    def stop(*args, **kwargs):
        raise StopHere("stop")

    runtime.workbench = stop
    monkeypatch.setattr("growbridge.runtime.build_runtime", fake_build)
    for name in (*ENV, "GROWBRIDGE_HEARTBEAT_HOST_URL", "GROWBRIDGE_HEARTBEAT_RUN_URL"):
        monkeypatch.delenv(name, raising=False)
    firecrest = ModuleType("firecrest")
    firecrest.ClientCredentialsAuth = lambda client_id, client_secret, token_uri: "auth"
    firecrest.v2 = SimpleNamespace(AsyncFirecrest=lambda firecrest_url, authorization: object())
    monkeypatch.setitem(sys.modules, "firecrest", firecrest)
    return SimpleNamespace(seen=seen, runtime=runtime)


def settings(tmp_path, templates=None, member="csc_robot"):
    return Settings(
        device="SIMULATED",
        token="x" * 32,
        data_dir=tmp_path / "data",
        auto_research=True,
        compute_templates_dir=templates,
        compute_member=member,
    )


@pytest.fixture
def templates(tmp_path):
    folder = tmp_path / "templates"
    folder.mkdir()
    (folder / "segment.json").write_text(json.dumps(TEMPLATE))
    return folder


async def test_serve_without_compute_settings_builds_a_runtime_without_compute(served, tmp_path):
    with pytest.raises(SystemExit):
        await cli._serve_auto_research(settings(tmp_path, member=None))

    assert "compute_backend" not in served.seen


async def test_serve_with_everything_configured_passes_the_backend_templates_and_member(
    served, tmp_path, templates, monkeypatch
):
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(SystemExit):
        await cli._serve_auto_research(settings(tmp_path, templates))

    assert served.seen["compute_backend"].system == "cpu"
    assert [t.id for t in served.seen["compute_templates"]] == ["segment"]
    assert served.seen["compute_members"] == {"researcher": "csc_robot"}
    assert served.runtime.compute.input_guard is not None  # inputs are scope-checked


async def test_serve_with_a_partial_setup_starts_without_compute(
    served, tmp_path, templates, monkeypatch, caplog
):
    for name, value in ENV.items():
        if name != "FIRECREST_ACCOUNT":
            monkeypatch.setenv(name, value)

    with pytest.raises(SystemExit):
        await cli._serve_auto_research(settings(tmp_path, templates))

    assert "compute_backend" not in served.seen
    assert "FIRECREST_ACCOUNT" in caplog.text and "s3cr3t" not in caplog.text


async def test_serve_with_a_bad_template_stops_before_the_runtime_is_built(
    served, tmp_path, templates, monkeypatch
):
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    (templates / "broken.json").write_text("{")

    with pytest.raises(SystemExit) as stopped:
        await cli._serve_auto_research(settings(tmp_path, templates))

    assert "broken.json" in str(stopped.value) and served.seen == {}
