import re

from fastapi.testclient import TestClient

from growbridge.api import create_app
from growbridge.config import Settings

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


def test_workbench_page_is_served_with_the_security_headers(bench):
    response = bench.lan.get("/workbench")
    assert response.status_code == 200 and response.headers["content-security-policy"] == CSP


def test_workbench_page_has_no_inline_script_or_style(bench):
    html = bench.lan.get("/workbench").text
    assert "<style" not in html and " style=" not in html
    assert re.findall(r"<script(?![^>]*\bsrc=)", html) == []


def test_workbench_page_loads_only_same_origin_assets(bench):
    links = re.findall(r'(?:src|href)="([^"]+)"', bench.lan.get("/workbench").text)
    assert links and all(link.startswith("/assets/") for link in links)


def test_workbench_page_is_absent_without_the_workbench(tmp_path):
    settings = Settings(device="SIMULATED", token="s" * 32, data_dir=tmp_path)
    client = TestClient(create_app(settings, bridge=object(), workbench=None))
    assert client.get("/workbench").status_code == 404
