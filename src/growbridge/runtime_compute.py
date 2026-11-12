"""Assembly of the compute service for ``serve`` (architecture doc §9.4).

``compute_setup`` decides, from the settings and the environment, whether the service starts:
only when the seven FireCREST variables, ``compute_templates_dir`` and ``compute_member`` are all
set. A partial setup starts nothing and logs which names are missing (never their values); a
fully configured but broken one (a bad template, a missing package, an invalid project setting)
stops the start with an error that names the file or variable.

``install_input_guard`` gives the service its scope check for model-named inputs: every input
must be a verified snapshot of the task's own project without held-out outcomes, the same rules
as ``run_local_analysis``. Without the guard the service refuses all inputs.
"""

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from growbridge.agents.handlers_common import Deps, scoped_snapshot
from growbridge.agents.handlers_researcher import ROLE
from growbridge.archive import snapshot as snapshots
from growbridge.compute.backend import BackendUnavailable, JobTemplate, SubmitRejected
from growbridge.compute.firecrest import ENV_VARIABLES, FirecrestBackend
from growbridge.compute.service import template_problem
from growbridge.config import Settings
from growbridge.ports import Denied

log = logging.getLogger(__name__)
MAX_TEMPLATE_BYTES = 1 << 20


class ComputeConfigError(ValueError):
    """The compute settings are present but unusable; the message never holds a credential."""


@dataclass(frozen=True)
class LoadedTemplate:
    template: JobTemplate
    file: str
    sha256: str


@dataclass(frozen=True)
class ComputeSetup:
    backend: Any
    templates: tuple[JobTemplate, ...]
    members: Mapping[str, str]

    def __repr__(self) -> str:
        return f"ComputeSetup(templates={[t.id for t in self.templates]})"


def _problems(error: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors())


def _load_one(path: Path) -> LoadedTemplate:
    raw = path.read_bytes()
    if len(raw) > MAX_TEMPLATE_BYTES:
        raise ComputeConfigError(f"{path.name}: larger than {MAX_TEMPLATE_BYTES} bytes")
    try:
        template = JobTemplate.model_validate(json.loads(raw))
    except json.JSONDecodeError as error:
        raise ComputeConfigError(f"{path.name}: not valid JSON ({error.msg})") from None
    except ValidationError as error:
        raise ComputeConfigError(f"{path.name}: {_problems(error)}") from None
    unknown = sorted(set(template.result_changing) - set(template.parameters))
    if unknown:  # a typo here would silently switch off the new-analysis-version rule
        raise ComputeConfigError(f"{path.name}: result_changing names unknown parameters {unknown}")
    problem = template_problem(template)
    if problem is not None:
        raise ComputeConfigError(f"{path.name}: {problem}")
    try:
        FirecrestBackend.check_template(template)
    except SubmitRejected as error:
        raise ComputeConfigError(f"{path.name}: {error}") from None
    return LoadedTemplate(template, path.name, hashlib.sha256(raw).hexdigest())


def load_templates(directory: Path) -> list[LoadedTemplate]:
    """Every ``*.json`` file of ``directory`` as a validated template; the first bad one fails."""
    if not directory.is_dir():
        raise ComputeConfigError(f"compute_templates_dir {str(directory)!r} is not a directory")
    files = sorted(directory.glob("*.json"))
    if not files:
        raise ComputeConfigError(f"no templates (*.json) in {str(directory)!r}")
    loaded: list[LoadedTemplate] = []
    seen: dict[tuple[str, int], str] = {}
    for path in files:
        item = _load_one(path)
        key = (item.template.id, item.template.version)
        if key in seen:
            raise ComputeConfigError(
                f"{path.name}: template {key[0]} version {key[1]} is already in {seen[key]}"
            )
        seen[key] = path.name
        loaded.append(item)
        log.info(
            "compute template %s version %s sha256=%s (%s)", key[0], key[1], item.sha256, path.name
        )
    return loaded


def compute_setup(
    settings: Settings, environ: Mapping[str, str], client: Any = None
) -> ComputeSetup | None:
    """The backend, templates and member map, or ``None`` when the compute service is not
    configured. ``client`` replaces the real FirecREST client (tests)."""
    directory, member = settings.compute_templates_dir, settings.compute_member
    missing = [name for name in ENV_VARIABLES if not environ.get(name)]
    missing += [n for n, value in (("compute_templates_dir", directory), ("compute_member", member))
                if not value]  # fmt: skip
    if len(missing) == len(ENV_VARIABLES) + 2:
        return None  # nothing configured: not an error and not worth a log line
    if missing or directory is None or not member:
        log.warning("compute service not started; not configured: %s", ", ".join(missing))
        return None
    templates = tuple(item.template for item in load_templates(directory))
    try:
        backend = FirecrestBackend(client=client, environ=environ)
    except BackendUnavailable as error:
        raise ComputeConfigError(f"FirecREST: {error}") from None
    log.info(
        "compute service configured: %d template(s), system %s", len(templates), backend.system
    )
    return ComputeSetup(backend, templates, {ROLE: member})


def compute_options(settings: Settings, environ: Mapping[str, str]) -> dict[str, Any]:
    """The ``build_runtime`` keyword arguments for the compute service; empty when it is off."""
    setup = compute_setup(settings, environ)
    if setup is None:
        return {}
    return {
        "compute_backend": setup.backend,
        "compute_templates": setup.templates,
        "compute_members": setup.members,
    }


def install_input_guard(runtime: Any) -> None:
    """Make the compute service accept only inputs the researcher could analyse locally."""
    if runtime.compute is None:
        return
    deps = Deps(
        workflow=runtime.workflow,
        control=runtime.control,
        archive=runtime.archive,
        tasks=runtime.tasks,
        clock=runtime.clock,
        work_root=runtime.archive.root,
        holdout=runtime.holdout,
    )

    def guard(task_id: str, ref: str) -> None:
        task = runtime.tasks.get(task_id)
        snap = scoped_snapshot(deps, task, ref.partition("/")[0])  # project and holdout first
        if runtime.archive.is_invalid(snap.id):
            raise Denied("state", f"snapshot {snap.id} was invalidated by a later correction")
        if not snapshots.verify(runtime.archive, snap.id):
            raise Denied("snapshot_incomplete", f"snapshot {snap.id} fails verification")

    runtime.compute.input_guard = guard
