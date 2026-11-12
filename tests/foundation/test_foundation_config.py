"""Loading the configuration file: paths, the report time zone and the price of a role's model."""

from pathlib import Path

import pytest

from growbridge.config import RoleModel, load

TOKEN = "x" * 32


def write(tmp_path, extra: str = "") -> Path:
    path = tmp_path / "config.toml"
    path.write_text(f'device = "SIMULATED"\ntoken = "{TOKEN}"\ndata_dir = "~/gb-data"\n{extra}')
    return path


def test_backup_dir_expands_the_home_directory_like_data_dir(tmp_path):
    settings = load(write(tmp_path, 'backup_dir = "~/gb-backups"\n'))

    assert settings.data_dir == Path.home() / "gb-data"
    assert settings.backup_dir == Path.home() / "gb-backups"


def test_backup_dir_stays_unset_when_it_is_not_given(tmp_path):
    assert load(write(tmp_path)).backup_dir is None


def test_unknown_report_timezone_is_refused_on_load(tmp_path):
    with pytest.raises(ValueError, match="report_timezone"):
        load(write(tmp_path, 'report_timezone = "Mars/Olympus"\n'))


def test_known_report_timezone_is_accepted(tmp_path):
    settings = load(write(tmp_path, 'report_timezone = "Europe/Helsinki"\n'))

    assert settings.report_timezone == "Europe/Helsinki"


def test_role_on_another_model_without_a_price_is_refused():
    with pytest.raises(ValueError, match="input_per_mtok"):
        RoleModel(model="some-other-model")


def test_role_price_fields_must_be_given_together():
    with pytest.raises(ValueError, match="together"):
        RoleModel(input_per_mtok=1.0)


def test_role_on_the_default_model_needs_no_price():
    role = RoleModel()

    assert role.input_per_mtok is None and role.output_per_mtok is None


def test_role_price_is_read_from_the_roles_table(tmp_path):
    table = (
        '[roles.planner]\nmodel = "some-other-model"\ninput_per_mtok = 1.0\noutput_per_mtok = 5.0\n'
    )

    role = load(write(tmp_path, table)).roles["planner"]

    assert (role.input_per_mtok, role.output_per_mtok) == (1.0, 5.0)
