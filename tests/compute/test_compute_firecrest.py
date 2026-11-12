import sys
from types import ModuleType

import pytest

from growbridge.compute.backend import BackendUnavailable
from growbridge.compute.firecrest import FirecrestBackend

VARIABLES = (
    "FIRECREST_URL",
    "FIRECREST_TOKEN_URL",
    "FIRECREST_CLIENT_ID",
    "FIRECREST_CLIENT_SECRET",
    "FIRECREST_SYSTEM",
    "FIRECREST_ACCOUNT",
    "FIRECREST_WORKDIR",
)
VALUES = {"FIRECREST_SYSTEM": "cpu", "FIRECREST_ACCOUNT": "project_1", "FIRECREST_WORKDIR": "/s/w"}


def test_firecrest_refuses_without_the_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "firecrest", None)
    monkeypatch.setitem(sys.modules, "pyfirecrest", None)
    with pytest.raises(BackendUnavailable, match="pyfirecrest"):
        FirecrestBackend()


@pytest.mark.parametrize("missing", VARIABLES)
def test_firecrest_refuses_when_a_variable_is_missing(monkeypatch, missing):
    monkeypatch.setitem(sys.modules, "firecrest", ModuleType("firecrest"))
    monkeypatch.setitem(sys.modules, "pyfirecrest", ModuleType("pyfirecrest"))
    for name in VARIABLES:
        monkeypatch.setenv(name, VALUES.get(name, "x"))
    monkeypatch.delenv(missing)
    with pytest.raises(BackendUnavailable, match=missing):
        FirecrestBackend()
