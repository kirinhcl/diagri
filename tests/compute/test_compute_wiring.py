"""What `serve` does with the compute settings: load templates, decide, build, report gaps."""

import hashlib
import json
import logging
import sys

import pytest
from fake_firecrest import FakeFirecrest

from growbridge.config import Settings
from growbridge.runtime_compute import ComputeConfigError, compute_setup, load_templates

SECRET = "s3cr3t-client-secret"
ENV = {
    "FIRECREST_URL": "https://api.example.test/v1",
    "FIRECREST_TOKEN_URL": "https://auth.example.test/token",
    "FIRECREST_CLIENT_ID": "robot-account",
    "FIRECREST_CLIENT_SECRET": SECRET,
    "FIRECREST_SYSTEM": "cpu",
    "FIRECREST_ACCOUNT": "project_2001234",
    "FIRECREST_WORKDIR": "/scratch/project_2001234/diagri",
}
TEMPLATE = {
    "id": "segment",
    "version": 1,
    "script": '#!/bin/bash\n#SBATCH --time=00:10:00\npython run.py "$DIAGRI_PARAM_EPOCHS"\n',
    "parameters": {"epochs": {"kind": "int", "minimum": 1, "maximum": 100}},
    "max_cpu_hours": 10,
    "max_storage_gb": 5,
    "result_changing": ["epochs"],
}


def write(folder, name, body):
    (folder / name).write_text(json.dumps(body) if not isinstance(body, str) else body)


@pytest.fixture
def folder(tmp_path):
    path = tmp_path / "templates"
    path.mkdir()
    write(path, "segment.json", TEMPLATE)
    return path


def settings(tmp_path, folder=None, member="csc_robot"):
    return Settings(
        device="SIMULATED",
        token="x" * 32,
        data_dir=tmp_path,
        auto_research=True,
        compute_templates_dir=folder,
        compute_member=member,
    )


# --- templates ---------------------------------------------------------------------------------


def test_compute_templates_load_with_the_digest_of_their_file(folder):
    (loaded,) = load_templates(folder)

    assert (loaded.template.id, loaded.template.version) == ("segment", 1)
    assert loaded.file == "segment.json"
    assert loaded.sha256 == hashlib.sha256((folder / "segment.json").read_bytes()).hexdigest()


def test_compute_loaded_templates_are_logged_with_id_version_and_digest(folder, caplog):
    with caplog.at_level(logging.INFO, logger="growbridge.runtime_compute"):
        (loaded,) = load_templates(folder)

    line = next(r.getMessage() for r in caplog.records if "segment" in r.getMessage())
    assert "1" in line and loaded.sha256 in line


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("{not json", "not valid"),
        ({**TEMPLATE, "extra_field": 1}, "extra_field"),
        ({k: v for k, v in TEMPLATE.items() if k != "script"}, "script"),
        ({**TEMPLATE, "result_changing": ["nope"]}, "result_changing"),
        ({**TEMPLATE, "script": "python run.py\n"}, "interpreter"),
        ({**TEMPLATE, "script": "#!/bin/bash\n#SBATCH -J mine\n#SBATCH -t 5\n"}, "job name"),
        ({**TEMPLATE, "script": "#!/bin/bash\nrun\n"}, "time limit"),
        (
            {**TEMPLATE, "parameters": {"label": {"kind": "str"}}, "result_changing": []},
            "pattern",
        ),
        (
            {
                **TEMPLATE,
                "parameters": {"label": {"kind": "str", "pattern": "[a-z]+", "default": "A1"}},
                "result_changing": [],
            },
            "default",
        ),
        (
            {
                **TEMPLATE,
                "parameters": {"label": {"kind": "str", "pattern": "[unclosed"}},
                "result_changing": [],
            },
            "pattern",
        ),
        ({**TEMPLATE, "max_cpu_hours": -1}, "max_cpu_hours"),
        ({**TEMPLATE, "max_storage_gb": float("inf")}, "max_storage_gb"),
        (
            {**TEMPLATE, "parameters": {"bad name": {"kind": "int"}}, "result_changing": []},
            "environment variable",
        ),
    ],
)
def test_compute_a_bad_template_names_its_file(folder, body, reason):
    write(folder, "broken.json", body)
    with pytest.raises(ComputeConfigError) as info:
        load_templates(folder)
    assert "broken.json" in str(info.value) and reason in str(info.value)


def test_compute_duplicate_template_versions_are_refused(folder):
    write(folder, "again.json", TEMPLATE)
    with pytest.raises(ComputeConfigError, match="segment"):
        load_templates(folder)


def test_compute_an_empty_or_missing_template_directory_is_refused(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ComputeConfigError, match="no templates"):
        load_templates(empty)
    with pytest.raises(ComputeConfigError, match="not a directory"):
        load_templates(tmp_path / "missing")


# --- the decision --------------------------------------------------------------------------------


def test_compute_nothing_configured_means_no_service_and_no_noise(tmp_path, caplog):
    with caplog.at_level(logging.INFO):
        assert compute_setup(settings(tmp_path, member=None), {}) is None
    assert caplog.records == []


def test_compute_everything_configured_builds_the_backend_and_the_member_map(
    tmp_path, folder, caplog
):
    with caplog.at_level(logging.INFO):
        setup = compute_setup(settings(tmp_path, folder), ENV, client=FakeFirecrest())

    assert setup is not None
    assert [t.id for t in setup.templates] == ["segment"]
    assert setup.members == {"researcher": "csc_robot"}
    assert SECRET not in caplog.text and SECRET not in repr(setup)


@pytest.mark.parametrize("missing", sorted(ENV))
def test_compute_a_partial_setup_starts_nothing_and_names_what_is_missing(
    tmp_path, folder, caplog, missing
):
    env = {k: v for k, v in ENV.items() if k != missing}
    with caplog.at_level(logging.WARNING):
        assert compute_setup(settings(tmp_path, folder), env, client=FakeFirecrest()) is None

    assert missing in caplog.text
    assert SECRET not in caplog.text and "api.example.test" not in caplog.text


@pytest.mark.parametrize("what", ["templates", "member"])
def test_compute_a_partial_setup_without_templates_or_member_starts_nothing(
    tmp_path, folder, caplog, what
):
    chosen = settings(
        tmp_path,
        folder if what != "templates" else None,
        "csc_robot" if what != "member" else None,
    )
    with caplog.at_level(logging.WARNING):
        assert compute_setup(chosen, ENV, client=FakeFirecrest()) is None
    assert ("compute_templates_dir" if what == "templates" else "compute_member") in caplog.text


def test_compute_fully_configured_but_no_pyfirecrest_stops_the_start(tmp_path, folder, monkeypatch):
    monkeypatch.setitem(sys.modules, "firecrest", None)
    with pytest.raises(ComputeConfigError, match="pyfirecrest"):
        compute_setup(settings(tmp_path, folder), ENV)


def test_compute_a_bad_template_stops_the_start_even_with_a_fake_client(tmp_path, folder):
    write(folder, "broken.json", "{")
    with pytest.raises(ComputeConfigError, match="broken.json"):
        compute_setup(settings(tmp_path, folder), ENV, client=FakeFirecrest())


def test_compute_invalid_firecrest_settings_stop_the_start_without_their_values(tmp_path, folder):
    env = {**ENV, "FIRECREST_SYSTEM": "laptop"}
    with pytest.raises(ComputeConfigError) as info:
        compute_setup(settings(tmp_path, folder), env, client=FakeFirecrest())
    assert "FIRECREST_SYSTEM" in str(info.value) and "laptop" not in str(info.value)


@pytest.mark.parametrize(
    "spec",
    [
        {"kind": "str", "pattern": "[a-z0-9_]{1,32}"},
        {"kind": "str", "choices": ["small", "large"]},
        {"kind": "int", "minimum": 1, "maximum": 10},
    ],
)
def test_compute_a_free_text_parameter_needs_a_pattern_but_other_kinds_do_not(folder, spec):
    write(folder, "segment.json", {**TEMPLATE, "parameters": {"p": spec}, "result_changing": []})
    assert len(load_templates(folder)) == 1
