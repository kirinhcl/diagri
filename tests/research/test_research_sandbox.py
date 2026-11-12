import json
import os
import socket
import sys
import textwrap
from pathlib import Path

import pytest

from growbridge.ports import Denied
from growbridge.research.sandbox import (
    SANDBOX_EXEC,
    RefusingSandbox,
    SeatbeltSandbox,
    make_sandbox,
)

needs_seatbelt = pytest.mark.skipif(
    sys.platform != "darwin" or not os.path.exists(SANDBOX_EXEC),
    reason="sandbox-exec is only available on macOS",
)
FAKE_CREDENTIAL = "fake-secret-for-test-0000"
TIMEOUT = 5.0


@pytest.fixture
def dirs(tmp_path):
    snapshot = tmp_path / "snapshot"
    out = tmp_path / "out"
    snapshot.mkdir()
    out.mkdir()
    (snapshot / "samples.jsonl").write_text('{"v": 1}\n')
    return snapshot, out


def write_script(tmp_path, body: str):
    path = tmp_path / "job.py"
    path.write_text(textwrap.dedent(body))
    return path


def test_refusing_sandbox_denies_every_run(tmp_path, dirs):
    snapshot, out = dirs
    script = write_script(tmp_path, "print('x')")

    with pytest.raises(Denied) as caught:
        RefusingSandbox().run(script, snapshot, out, TIMEOUT)

    assert caught.value.code == "sandbox_unavailable"


def test_make_sandbox_picks_a_backend_for_this_platform():
    backend = make_sandbox()

    if sys.platform == "darwin" and os.path.exists(SANDBOX_EXEC):
        assert isinstance(backend, SeatbeltSandbox)
    else:
        assert isinstance(backend, RefusingSandbox)


@needs_seatbelt
def test_sandbox_runs_a_script_that_reads_the_snapshot_and_writes_the_output(tmp_path, dirs):
    snapshot, out = dirs
    script = write_script(
        tmp_path,
        """
        import pathlib, sys
        text = pathlib.Path(sys.argv[1], "samples.jsonl").read_text()
        pathlib.Path(sys.argv[2], "result.txt").write_text(text.upper())
        print("finished")
        """,
    )

    result = SeatbeltSandbox().run(script, snapshot, out, TIMEOUT)

    assert result.exit_code == 0, result.stderr
    assert "finished" in result.stdout
    assert (out / "result.txt").read_text() == '{"V": 1}\n'


@needs_seatbelt
def test_network_access_from_the_sandbox_fails(tmp_path, dirs):
    snapshot, out = dirs
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    script = write_script(
        tmp_path,
        f"""
        import json, pathlib, socket, sys
        try:
            socket.create_connection(("127.0.0.1", {port}), timeout=2).close()
            outcome = "connected"
        except OSError as error:
            outcome = "blocked: " + type(error).__name__
        pathlib.Path(sys.argv[2], "net.json").write_text(json.dumps(outcome))
        """,
    )
    try:
        result = SeatbeltSandbox().run(script, snapshot, out, TIMEOUT)
    finally:
        listener.close()

    assert result.exit_code == 0, result.stderr
    assert json.loads((out / "net.json").read_text()).startswith("blocked")


@needs_seatbelt
def test_writing_into_the_snapshot_directory_fails(tmp_path, dirs):
    snapshot, out = dirs
    script = write_script(
        tmp_path,
        """
        import pathlib, sys
        pathlib.Path(sys.argv[1], "samples.jsonl").write_text("tampered")
        """,
    )

    result = SeatbeltSandbox().run(script, snapshot, out, TIMEOUT)

    assert result.exit_code != 0
    assert (snapshot / "samples.jsonl").read_text() == '{"v": 1}\n'


@needs_seatbelt
def test_writing_next_to_the_output_directory_fails(tmp_path, dirs):
    snapshot, out = dirs
    script = write_script(
        tmp_path,
        """
        import pathlib, sys
        pathlib.Path(sys.argv[2]).parent.joinpath("escape.txt").write_text("x")
        """,
    )

    result = SeatbeltSandbox().run(script, snapshot, out, TIMEOUT)

    assert result.exit_code != 0
    assert not (tmp_path / "escape.txt").exists()


@needs_seatbelt
def test_the_child_cannot_see_credentials_from_the_parent_environment(tmp_path, dirs, monkeypatch):
    monkeypatch.setenv("FAKE_CREDENTIAL", FAKE_CREDENTIAL)
    snapshot, out = dirs
    script = write_script(
        tmp_path,
        """
        import json, os, pathlib, sys
        pathlib.Path(sys.argv[2], "env.json").write_text(json.dumps(dict(os.environ)))
        print(os.environ.get("FAKE_CREDENTIAL"))
        """,
    )

    result = SeatbeltSandbox().run(script, snapshot, out, TIMEOUT)

    assert result.exit_code == 0, result.stderr
    assert FAKE_CREDENTIAL not in result.stdout
    assert "None" in result.stdout
    assert FAKE_CREDENTIAL not in (out / "env.json").read_text()


@needs_seatbelt
def test_a_script_that_runs_too_long_is_stopped(tmp_path, dirs):
    snapshot, out = dirs
    script = write_script(tmp_path, "import time\ntime.sleep(30)\n")

    result = SeatbeltSandbox().run(script, snapshot, out, 1.0)

    assert result.timed_out is True
    assert result.exit_code != 0


FAKE_TOKEN = "fake-bridge-token-0000"


@pytest.fixture
def secret_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("secret_root")  # not under the script's directory
    (root / "token").write_text(FAKE_TOKEN)
    return root


def test_default_deny_list_contains_the_home_directory():
    assert Path.home().resolve() in SeatbeltSandbox().deny_read


@needs_seatbelt
def test_a_file_under_a_denied_root_cannot_be_read(tmp_path, dirs, secret_root):
    snapshot, out = dirs
    script = write_script(
        tmp_path,
        f"""
        import pathlib, sys
        text = pathlib.Path({str(secret_root / "token")!r}).read_text()
        pathlib.Path(sys.argv[2], "stolen.txt").write_text(text)
        print(text)
        """,
    )

    result = SeatbeltSandbox(deny_read=[secret_root]).run(script, snapshot, out, TIMEOUT)

    assert result.exit_code != 0
    assert FAKE_TOKEN not in result.stdout
    assert not (out / "stolen.txt").exists()


@needs_seatbelt
def test_denied_roots_cannot_be_listed_or_copied_either(tmp_path, dirs, secret_root):
    snapshot, out = dirs
    script = write_script(
        tmp_path,
        f"""
        import os, pathlib, shutil, sys
        for step in (
            lambda: os.listdir({str(secret_root)!r}),
            lambda: shutil.copy({str(secret_root / "token")!r}, sys.argv[2]),
        ):
            try:
                step()
                print("LEAK")
            except OSError:
                print("blocked")
        """,
    )

    result = SeatbeltSandbox(deny_read=[secret_root]).run(script, snapshot, out, TIMEOUT)

    assert "LEAK" not in result.stdout
    assert result.stdout.count("blocked") == 2
    assert list(out.iterdir()) == []


@needs_seatbelt
def test_snapshot_and_output_stay_usable_inside_a_denied_root(tmp_path, secret_root):
    snapshot = secret_root / "snapshot"
    out = secret_root / "out"
    snapshot.mkdir()
    out.mkdir()
    (snapshot / "samples.jsonl").write_text("rows")
    script = write_script(
        tmp_path,
        """
        import pathlib, sys
        text = pathlib.Path(sys.argv[1], "samples.jsonl").read_text()
        pathlib.Path(sys.argv[2], "copy.txt").write_text(text)
        """,
    )

    result = SeatbeltSandbox(deny_read=[secret_root]).run(script, snapshot, out, TIMEOUT)

    assert result.exit_code == 0, result.stderr
    assert (out / "copy.txt").read_text() == "rows"


@needs_seatbelt
def test_the_default_profile_denies_home_but_python_still_starts(tmp_path, dirs):
    snapshot, out = dirs
    probe = Path.home() / ".zshrc"
    script = write_script(
        tmp_path,
        f"""
        import pathlib
        try:
            pathlib.Path({str(probe)!r}).read_bytes()
            print("LEAK")
        except OSError:
            print("blocked")
        """,
    )

    result = SeatbeltSandbox().run(script, snapshot, out, TIMEOUT)

    assert result.exit_code == 0, result.stderr
    assert "blocked" in result.stdout


@needs_seatbelt
def test_the_script_cannot_signal_other_processes(tmp_path, dirs):
    snapshot, out = dirs
    script = write_script(
        tmp_path,
        """
        import os
        try:
            os.kill(os.getppid(), 0)
            print("LEAK")
        except OSError:
            print("blocked")
        """,
    )

    result = SeatbeltSandbox().run(script, snapshot, out, TIMEOUT)

    assert result.exit_code == 0, result.stderr
    assert "blocked" in result.stdout
    assert "LEAK" not in result.stdout


@needs_seatbelt
def test_a_file_in_an_unrelated_directory_cannot_be_read(tmp_path, dirs, tmp_path_factory):
    snapshot, out = dirs
    elsewhere = tmp_path_factory.mktemp("growbridge-helper")
    pid_file = elsewhere / "helper.pid"
    pid_file.write_text("12345")
    script = write_script(
        tmp_path,
        f"""
        import pathlib
        try:
            print(pathlib.Path({str(pid_file)!r}).read_text())
        except OSError:
            print("blocked")
        """,
    )

    result = SeatbeltSandbox(deny_read=[]).run(script, snapshot, out, TIMEOUT)

    assert result.exit_code == 0, result.stderr
    assert "12345" not in result.stdout
    assert "blocked" in result.stdout


@needs_seatbelt
def test_standard_library_imports_still_work_under_deny_by_default(tmp_path, dirs):
    snapshot, out = dirs
    script = write_script(
        tmp_path,
        """
        import json, statistics, csv, datetime, math, sqlite3
        print(statistics.fmean([1, 2, 3]))
        """,
    )

    result = SeatbeltSandbox().run(script, snapshot, out, TIMEOUT)

    assert result.exit_code == 0, result.stderr
    assert "2.0" in result.stdout


@needs_seatbelt
def test_a_data_directory_outside_home_is_unreadable_except_the_mounted_snapshot(
    tmp_path, tmp_path_factory
):
    """The runtime denies ``data_dir`` wherever it lives; only the snapshot mounted for the run
    and the run's own folder are allowed back (seatbelt applies the last matching rule)."""
    data_dir = tmp_path_factory.mktemp("data_dir")  # not under $HOME
    assert Path.home().resolve() not in data_dir.resolve().parents
    own = data_dir / "archive" / "snapshots" / "own"
    other = data_dir / "archive" / "snapshots" / "other"
    own.mkdir(parents=True)
    other.mkdir(parents=True)
    (own / "measurements.jsonl").write_text("own rows")
    (other / "measurements.jsonl").write_text("HELD-OUT-ROWS")
    (data_dir / "agents.db").write_text("DATABASE-CONTENT")
    out = data_dir / "analysis" / "run-1" / "out"
    out.mkdir(parents=True)
    script = write_script(
        tmp_path,
        f"""
        import pathlib, sys
        def attempt(path):
            try:
                return pathlib.Path(path).read_text()
            except OSError:
                return "blocked"
        print("own:", attempt(sys.argv[1] + "/measurements.jsonl"))
        print("sibling:", attempt({str(other / "measurements.jsonl")!r}))
        print("database:", attempt({str(data_dir / "agents.db")!r}))
        print("parent listing:", attempt({str(data_dir / "archive")!r}))
        pathlib.Path(sys.argv[2], "result.txt").write_text("written")
        """,
    )

    result = SeatbeltSandbox(deny_read=[data_dir]).run(script, own, out, TIMEOUT)

    assert result.exit_code == 0, result.stderr
    assert "own: own rows" in result.stdout
    assert "sibling: blocked" in result.stdout
    assert "database: blocked" in result.stdout
    assert "HELD-OUT-ROWS" not in result.stdout and "DATABASE-CONTENT" not in result.stdout
    assert (out / "result.txt").read_text() == "written"
