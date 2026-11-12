"""FirecrestBackend against a fake client: no pyfirecrest, no network."""

import hashlib
import sys
from types import ModuleType, SimpleNamespace

import pytest
from fake_firecrest import FakeFirecrest

from growbridge.compute.backend import (
    BackendError,
    BackendUnavailable,
    JobTemplate,
    OutputTooLarge,
    ParamSpec,
    SubmitRejected,
)
from growbridge.compute.firecrest import MAX_OUTPUT_FILES, FirecrestBackend

WORKDIR = "/scratch/project_2001234/diagri"
NAME = "gb-att_abc123"
JOB_DIR = f"{WORKDIR}/{NAME}"
BIG = 10**9  # a limit no test output comes near
SECRET = "s3cr3t-client-secret"
SCRIPT = '#!/bin/bash\n#SBATCH --time=00:10:00\npython run.py "$DIAGRI_PARAM_EPOCHS"\n'
BASE_ENV = {
    "FIRECREST_SYSTEM": "cpu",
    "FIRECREST_ACCOUNT": "project_2001234",
    "FIRECREST_WORKDIR": WORKDIR,
}
CREDENTIALS = {
    "FIRECREST_URL": "https://api.example.test/v1",
    "FIRECREST_TOKEN_URL": "https://auth.example.test/token",
    "FIRECREST_CLIENT_ID": "robot-account",
    "FIRECREST_CLIENT_SECRET": SECRET,
}


def template(script: str = SCRIPT) -> JobTemplate:
    return JobTemplate(
        id="seg",
        version=1,
        script=script,
        parameters={
            "epochs": ParamSpec(kind="int", minimum=1, maximum=100),
            "label": ParamSpec(kind="str", default="x"),
        },
        max_cpu_hours=10.0,
        max_storage_gb=5.0,
    )


@pytest.fixture
def client():
    return FakeFirecrest()


@pytest.fixture
def backend(client):
    return FirecrestBackend(client=client, environ=BASE_ENV)


@pytest.fixture
def inputs(tmp_path):
    folder = tmp_path / "snap"
    (folder / "nested").mkdir(parents=True)
    (folder / "samples.jsonl").write_text('{"a": 1}\n')
    (folder / "nested" / "more.jsonl").write_text('{"b": 2}\n')
    return {"images": str(folder)}


async def submitted(backend, client, inputs=None, params=None, script=SCRIPT, name=NAME):
    return await backend.submit(name, template(script), params or {"epochs": 3}, inputs or {})


# --- construction ------------------------------------------------------------------------------


def test_firecrest_injected_client_needs_only_the_job_settings(client):
    backend = FirecrestBackend(client=client, environ=BASE_ENV)
    assert "cpu" in repr(backend)


@pytest.mark.parametrize("missing", list(BASE_ENV))
def test_firecrest_refuses_missing_job_settings_even_with_a_client(client, missing):
    env = {k: v for k, v in BASE_ENV.items() if k != missing}
    with pytest.raises(BackendUnavailable, match=missing):
        FirecrestBackend(client=client, environ=env)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("FIRECREST_SYSTEM", "dev"),
        ("FIRECREST_ACCOUNT", "project 1; rm"),
        ("FIRECREST_WORKDIR", "relative/path"),
        ("FIRECREST_WORKDIR", "/scratch/../etc"),
        ("FIRECREST_WORKDIR", "/"),
    ],
)
def test_firecrest_refuses_unsafe_job_settings(client, name, value):
    with pytest.raises(BackendUnavailable, match=name):
        FirecrestBackend(client=client, environ={**BASE_ENV, name: value})


def test_firecrest_default_client_is_built_from_the_documented_calls(monkeypatch):
    seen = {}
    module = ModuleType("firecrest")

    def auth(client_id, client_secret, token_uri):
        seen["auth"] = (client_id, client_secret, token_uri)
        return "auth-object"

    def firecrest(firecrest_url, authorization, verify=True):
        seen["client"] = (firecrest_url, authorization)
        return FakeFirecrest()

    module.ClientCredentialsAuth = auth
    module.v2 = SimpleNamespace(AsyncFirecrest=firecrest)
    monkeypatch.setitem(sys.modules, "firecrest", module)

    FirecrestBackend(environ={**BASE_ENV, **CREDENTIALS})

    assert seen["auth"] == ("robot-account", SECRET, "https://auth.example.test/token")
    assert seen["client"] == ("https://api.example.test/v1", "auth-object")


def test_firecrest_credentials_never_show_in_repr_or_errors(monkeypatch, client):
    monkeypatch.setitem(sys.modules, "firecrest", ModuleType("firecrest"))  # no auth class
    with pytest.raises(BackendUnavailable) as info:
        FirecrestBackend(environ={**BASE_ENV, **CREDENTIALS})
    assert SECRET not in str(info.value)
    assert SECRET not in repr(FirecrestBackend(client=client, environ={**BASE_ENV, **CREDENTIALS}))


async def test_firecrest_client_errors_do_not_echo_their_message(client, backend):
    client.fail["job_info"] = RuntimeError(f"401 token {SECRET}")
    with pytest.raises(BackendError) as info:
        await backend.status("1001")
    assert SECRET not in str(info.value)
    assert "RuntimeError" in str(info.value)


# --- submit ------------------------------------------------------------------------------------


async def test_firecrest_submit_uploads_inputs_and_submits_in_the_job_directory(
    backend, client, inputs
):
    job_id = await submitted(backend, client, inputs)

    assert job_id == "1001"
    assert f"{JOB_DIR}/out" in client.dirs
    assert client.files[f"{JOB_DIR}/inputs/images/samples.jsonl"] == b'{"a": 1}\n'
    assert client.files[f"{JOB_DIR}/inputs/images/nested/more.jsonl"] == b'{"b": 2}\n'
    (call,) = client.submitted
    assert call["system_name"] == "cpu"
    assert call["working_dir"] == JOB_DIR
    assert call["account"] == "project_2001234"
    assert all(u["account"] == "project_2001234" for u in client.called("upload"))


async def test_firecrest_parameters_reach_the_script_only_as_environment_variables(backend, client):
    hostile = '$(rm -rf /); "quoted" `x`'
    await submitted(backend, client, params={"epochs": 3, "label": hostile})

    (call,) = client.submitted
    assert hostile not in call["script_str"]
    assert call["script_str"] == SCRIPT.replace("\n", f"\n#SBATCH --job-name={NAME}\n", 1)
    assert call["env_vars"]["DIAGRI_PARAM_LABEL"] == hostile
    assert call["env_vars"]["DIAGRI_PARAM_EPOCHS"] == "3"
    assert call["env_vars"]["DIAGRI_OUTPUT_DIR"] == f"{JOB_DIR}/out"


async def test_firecrest_environment_values_are_strings(backend, client):
    tmpl = template().model_copy(
        update={
            "parameters": {
                "flag": ParamSpec(kind="bool"),
                "ratio": ParamSpec(kind="float"),
            }
        }
    )
    await backend.submit(NAME, tmpl, {"flag": True, "ratio": 0.5}, {})

    env = client.submitted[0]["env_vars"]
    assert (env["DIAGRI_PARAM_FLAG"], env["DIAGRI_PARAM_RATIO"]) == ("true", "0.5")


async def test_firecrest_input_paths_are_given_to_the_script_by_name(backend, client, inputs):
    await submitted(backend, client, inputs)
    assert client.submitted[0]["env_vars"]["DIAGRI_INPUT_IMAGES"] == f"{JOB_DIR}/inputs/images"


@pytest.mark.parametrize(
    "script",
    [
        "python run.py\n",  # no interpreter line
        "#!/bin/bash\n#SBATCH --job-name=other\nrun\n",
        "#!/bin/bash\n#SBATCH -J other\nrun\n",
    ],
)
async def test_firecrest_refuses_scripts_it_cannot_name_safely(backend, client, script):
    with pytest.raises(SubmitRejected):
        await submitted(backend, client, script=script)
    assert client.submitted == []


@pytest.mark.parametrize("name", ["../escape", "att_1", "gb-a b", "gb-", "gb-a/../b", ""])
async def test_firecrest_refuses_job_names_that_could_leave_the_work_directory(
    backend, client, name
):
    with pytest.raises(SubmitRejected):
        await submitted(backend, client, name=name)
    assert client.calls == []


@pytest.mark.parametrize(
    ("params", "inputs_"),
    [
        ({"epochs": 3, "bad name": 1}, {}),
        ({"epochs": 3}, {"bad name": "x"}),
        ({"epochs": 3, "Label": "a", "label": "b"}, {}),  # same variable after upper-casing
    ],
)
async def test_firecrest_refuses_names_that_cannot_be_environment_variables(
    backend, client, params, inputs_
):
    tmpl = template().model_copy(update={"parameters": {k: ParamSpec(kind="str") for k in params}})
    with pytest.raises(SubmitRejected):
        await backend.submit(NAME, tmpl, params, inputs_)
    assert client.submitted == []


async def test_firecrest_refuses_a_missing_input_before_touching_the_remote(backend, client):
    with pytest.raises(SubmitRejected):
        await submitted(backend, client, {"images": "/no/such/path"})
    assert client.calls == []


async def test_firecrest_refuses_a_symlink_in_an_input(backend, client, inputs, tmp_path):
    (tmp_path / "snap" / "link").symlink_to("/etc/hostname")
    with pytest.raises(SubmitRejected):
        await submitted(backend, client, inputs)
    assert client.submitted == []


async def test_firecrest_failed_upload_means_nothing_was_submitted(backend, client, inputs):
    client.fail["upload"] = ConnectionError("down")
    with pytest.raises(SubmitRejected):
        await submitted(backend, client, inputs)
    assert client.submitted == []


async def test_firecrest_failed_submit_call_is_uncertain_not_rejected(backend, client):
    client.fail["submit"] = TimeoutError("no reply")
    with pytest.raises(BackendError) as info:
        await submitted(backend, client)
    assert not isinstance(info.value, SubmitRejected)  # the job may exist: reconcile by name


@pytest.mark.parametrize("reply", [{}, {"jobId": None}, {"jobId": ""}, [], "ok", {"jobId": []}])
async def test_firecrest_submit_reply_without_a_job_id_is_uncertain(backend, client, reply):
    client.reply_override = reply
    with pytest.raises(BackendError) as info:
        await submitted(backend, client)
    assert not isinstance(info.value, SubmitRejected)


# --- find_by_name and status -------------------------------------------------------------------


async def test_firecrest_find_by_name_matches_the_exact_name(backend, client):
    await submitted(backend, client)
    await submitted(backend, client, name=f"{NAME}9")  # the fake filters by prefix

    found = await backend.find_by_name(NAME)

    assert found is not None
    assert (found.job_id, found.name, found.state) == ("1001", NAME, "queued")


async def test_firecrest_find_by_name_returns_none_when_there_is_no_job(backend):
    assert await backend.find_by_name(NAME) is None


async def test_firecrest_find_by_name_with_two_jobs_is_an_error(backend, client):
    await submitted(backend, client)
    await submitted(backend, client)  # the same name twice
    with pytest.raises(BackendError, match="more than one"):
        await backend.find_by_name(NAME)


STATES = {
    "PENDING": "queued",
    "CONFIGURING": "queued",
    "RUNNING": "running",
    "COMPLETING": "running",
    "COMPLETED": "completed",
    "FAILED": "failed",
    "TIMEOUT": "failed",
    "OUT_OF_MEMORY": "failed",
    "NODE_FAIL": "failed",
    "CANCELLED": "cancelled",
    "CANCELLED by 1001": "cancelled",
    # terminal: the job will never run again
    "DEADLINE": "failed",
    "PREEMPTED": "failed",
    "BOOT_FAIL": "failed",
    "REVOKED": "failed",
    # not terminal: the job is still held by the scheduler, so it must keep being polled
    "REQUEUED": "queued",
    "REQUEUE_HOLD": "queued",
    "SUSPENDED": "running",
    "STOPPED": "running",
    "running": "running",  # case does not matter
}


@pytest.mark.parametrize(("raw", "expected"), list(STATES.items()))
async def test_firecrest_status_maps_documented_slurm_states(backend, client, raw, expected):
    job_id = await submitted(backend, client)
    client.set_state(job_id, raw)

    assert (await backend.status(job_id)).state == expected


@pytest.mark.parametrize("raw", ["WEIRD", "RESIZING", "", "COMPLETED_MAYBE", None, 7, ["A", "B"]])
async def test_firecrest_unknown_state_is_never_completed(backend, client, raw):
    job_id = await submitted(backend, client)
    client.set_state(job_id, raw)

    with pytest.raises(BackendError) as info:
        await backend.status(job_id)
    assert repr(raw) in str(info.value)


async def test_firecrest_status_reports_no_usage(backend, client):
    job_id = await submitted(backend, client)
    client.set_state(job_id, "COMPLETED")

    job = await backend.status(job_id)

    assert (job.cpu_hours_used, job.storage_gb_used) == (None, None)  # the API has none


@pytest.mark.parametrize(
    "entry",
    [None, "x", {"jobId": 1}, {"jobId": 1, "name": NAME}, {"jobId": 1, "name": NAME, "status": 3}],
)
async def test_firecrest_malformed_job_info_is_an_error(backend, client, entry):
    job_id = await submitted(backend, client)
    client.jobs[0] = entry
    with pytest.raises(BackendError):
        await backend.status(job_id)


async def test_firecrest_status_of_an_unlisted_job_is_an_error(backend):
    with pytest.raises(BackendError, match="not listed"):
        await backend.status("4242")


# --- fetch, cleanup, cancel --------------------------------------------------------------------


async def finished(backend, client):
    job_id = await submitted(backend, client)
    client.set_state(job_id, "COMPLETED")
    client.put_output(job_id, "result.csv", b"a,b\n1,2\n")
    client.put_output(job_id, "model.bin", b"\x00\x01")
    return job_id


@pytest.mark.parametrize("shape", ["plain", "wrapped"])
async def test_firecrest_fetch_downloads_and_returns_remote_sha256(
    backend, client, tmp_path, shape
):
    job_id = await finished(backend, client)
    client.checksum_shape = shape
    out = tmp_path / "out"
    out.mkdir()

    sums = await backend.fetch(job_id, out, BIG)

    assert sums == {
        "model.bin": hashlib.sha256(b"\x00\x01").hexdigest(),
        "result.csv": hashlib.sha256(b"a,b\n1,2\n").hexdigest(),
    }
    assert (out / "result.csv").read_bytes() == b"a,b\n1,2\n"
    assert {c["system_name"] for c in client.called("download")} == {"cpu"}


@pytest.mark.parametrize(
    "change",
    [
        {"checksum_algorithm": "MD5"},
        {"checksum_override": "not-hex"},
        {"checksum_override": "ab" * 31},  # 62 hex digits
    ],
)
async def test_firecrest_fetch_refuses_a_checksum_it_cannot_trust(
    backend, client, tmp_path, change
):
    job_id = await finished(backend, client)
    for name, value in change.items():
        setattr(client, name, value)
    with pytest.raises(BackendError):
        await backend.fetch(job_id, tmp_path, BIG)


async def test_firecrest_fetch_accepts_sha256_spelled_without_a_hyphen(backend, client, tmp_path):
    job_id = await finished(backend, client)
    client.checksum_algorithm = "sha256"
    assert len(await backend.fetch(job_id, tmp_path, BIG)) == 2


@pytest.mark.parametrize(
    "listing",
    [
        [{"name": "../evil", "type": "-"}],
        [{"name": "a/b", "type": "-"}],
        [{"name": "", "type": "-"}],
        [{"name": "sub", "type": "d"}],  # nested directories are not fetched silently
        [{"name": "odd", "type": "?"}],
        [{"type": "-"}],
        ["result.csv"],
    ],
)
async def test_firecrest_fetch_refuses_listings_it_cannot_read_safely(
    backend, client, tmp_path, listing
):
    job_id = await finished(backend, client)
    client.listing_override = listing
    with pytest.raises(BackendError):
        await backend.fetch(job_id, tmp_path, BIG)
    assert client.called("download") == []


async def test_firecrest_cleanup_removes_only_the_job_directory(backend, client):
    job_id = await finished(backend, client)
    client.files[f"{WORKDIR}/keep.txt"] = b"other job"

    await backend.cleanup(job_id)

    assert [c["path"] for c in client.called("rm")] == [JOB_DIR]
    assert f"{WORKDIR}/keep.txt" in client.files
    assert not any(p.startswith(JOB_DIR) for p in client.files)


async def test_firecrest_cleanup_refuses_a_job_that_is_not_ours(backend, client):
    job_id = await submitted(backend, client)
    client.jobs[0]["name"] = "somebody-elses-job"
    with pytest.raises(BackendError):
        await backend.cleanup(job_id)
    assert client.called("rm") == []


async def test_firecrest_cancel_uses_cancel_job(backend, client):
    job_id = await submitted(backend, client)
    await backend.cancel(job_id)
    assert client.called("cancel_job") == [{"system_name": "cpu", "jobid": "1001"}]


async def test_firecrest_balance_is_unavailable_not_zero(backend):
    with pytest.raises(BackendUnavailable, match="balance"):
        await backend.balance()


async def test_firecrest_cleanup_by_name_removes_the_directory_without_a_job_id(backend, client):
    client.files[f"{JOB_DIR}/inputs/x/a.jsonl"] = b"{}"
    client.files[f"{WORKDIR}/keep.txt"] = b"other job"

    await backend.cleanup_by_name(NAME)

    assert [c["path"] for c in client.called("rm")] == [JOB_DIR]
    assert client.called("job_info") == []  # no listing needed: the name is the directory
    assert f"{WORKDIR}/keep.txt" in client.files


@pytest.mark.parametrize("name", ["../escape", "att_1", "gb-a b", ""])
async def test_firecrest_cleanup_by_name_refuses_names_of_other_jobs(backend, client, name):
    with pytest.raises(BackendError):
        await backend.cleanup_by_name(name)
    assert client.called("rm") == []


@pytest.mark.parametrize(
    ("script", "ok"),
    [
        ("#!/bin/bash\n#SBATCH --time=00:10:00\nrun\n", True),
        ("#!/bin/bash\n#SBATCH --time 00:10:00\nrun\n", True),
        ("#!/bin/bash\n#SBATCH -t 10\nrun\n", True),
        ("#!/bin/bash\n#SBATCH -t10\nrun\n", True),
        ("#!/bin/bash\nrun\n", False),
        ("#!/bin/bash\n# --time=10\nrun\n", False),  # a comment is not a directive
        ("#!/bin/bash\n#SBATCH --timeless\nrun\n", False),
    ],
)
def test_firecrest_a_template_must_bound_its_run_time(script, ok):
    tmpl = template(script)
    if ok:
        FirecrestBackend.check_template(tmpl)
    else:
        with pytest.raises(SubmitRejected, match="time"):
            FirecrestBackend.check_template(tmpl)


# --- the output limits -----------------------------------------------------------------------


async def two_outputs(backend, client, sizes=(10, 10)):
    job_id = await submitted(backend, client)
    client.set_state(job_id, "COMPLETED")
    for number, size in enumerate(sizes):
        client.put_output(job_id, f"part{number}.bin", b"x" * size)
    return job_id


def local_files(folder):
    return sorted(p.name for p in folder.iterdir())


async def test_firecrest_fetch_refuses_too_many_files_before_any_download(
    backend, client, tmp_path
):
    job_id = await submitted(backend, client)
    for number in range(MAX_OUTPUT_FILES + 1):
        client.put_output(job_id, f"f{number}", b"")

    with pytest.raises(OutputTooLarge, match="files"):
        await backend.fetch(job_id, tmp_path, BIG)

    assert client.called("download") == [] and local_files(tmp_path) == []


async def test_firecrest_fetch_accepts_exactly_the_file_limit(backend, client, tmp_path):
    job_id = await submitted(backend, client)
    for number in range(MAX_OUTPUT_FILES):
        client.put_output(job_id, f"f{number}", b"")

    assert len(await backend.fetch(job_id, tmp_path, BIG)) == MAX_OUTPUT_FILES


async def test_firecrest_fetch_refuses_a_total_over_the_limit_before_any_download(
    backend, client, tmp_path
):
    job_id = await two_outputs(backend, client, (60, 60))

    with pytest.raises(OutputTooLarge, match="bytes"):
        await backend.fetch(job_id, tmp_path, 100)

    assert client.called("download") == [] and local_files(tmp_path) == []


async def test_firecrest_fetch_accepts_a_total_exactly_at_the_limit(backend, client, tmp_path):
    job_id = await two_outputs(backend, client, (50, 50))
    assert len(await backend.fetch(job_id, tmp_path, 100)) == 2


@pytest.mark.parametrize("size", [None, "abc", "-1", -1, 1.5, True, [], "", "1e3"])
async def test_firecrest_fetch_refuses_an_entry_without_a_usable_size(
    backend, client, tmp_path, size
):
    job_id = await two_outputs(backend, client)
    entry = {"name": "part0.bin", "type": "-"}
    client.listing_override = [entry if size is None else {**entry, "size": size}]

    with pytest.raises(BackendError, match="size"):
        await backend.fetch(job_id, tmp_path, BIG)

    assert client.called("download") == [] and local_files(tmp_path) == []


async def test_firecrest_fetch_reads_a_size_given_as_digits(backend, client, tmp_path):
    job_id = await two_outputs(backend, client, (7,))
    client.listing_override = [{"name": "part0.bin", "type": "-", "size": "7"}]
    assert list(await backend.fetch(job_id, tmp_path, BIG)) == ["part0.bin"]


async def test_firecrest_fetch_aborts_when_files_turn_out_bigger_than_listed(
    backend, client, tmp_path
):
    job_id = await two_outputs(backend, client, (60, 60))  # really 120 bytes
    client.listing_override = [  # the listing says 10 bytes each, so the pre-check passes
        {"name": "part0.bin", "type": "-", "size": 10},
        {"name": "part1.bin", "type": "-", "size": 10},
    ]

    with pytest.raises(OutputTooLarge, match="limit"):
        await backend.fetch(job_id, tmp_path, 100)

    assert len(client.called("download")) == 2  # it only knew after the second
    assert local_files(tmp_path) == []  # nothing that was downloaded is left behind


async def test_firecrest_fetch_stops_at_the_file_that_passes_the_limit(backend, client, tmp_path):
    job_id = await two_outputs(backend, client, (200, 5))
    client.listing_override = [
        {"name": "part0.bin", "type": "-", "size": 1},
        {"name": "part1.bin", "type": "-", "size": 1},
    ]

    with pytest.raises(OutputTooLarge):
        await backend.fetch(job_id, tmp_path, 100)

    assert len(client.called("download")) == 1  # the second file was never started
    assert local_files(tmp_path) == []


async def test_firecrest_fetch_removes_only_what_it_downloaded(backend, client, tmp_path):
    (tmp_path / "keep.txt").write_text("not ours")
    job_id = await two_outputs(backend, client, (60, 60))

    with pytest.raises(OutputTooLarge):
        await backend.fetch(job_id, tmp_path, 100)

    assert local_files(tmp_path) == ["keep.txt"]


async def test_firecrest_output_limit_errors_say_which_limit_and_no_contents(
    backend, client, tmp_path
):
    job_id = await two_outputs(backend, client, (60, 60))
    with pytest.raises(OutputTooLarge) as info:
        await backend.fetch(job_id, tmp_path, 100)
    assert "120" in str(info.value) and "100" in str(info.value) and "xxx" not in str(info.value)
