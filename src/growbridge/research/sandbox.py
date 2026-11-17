"""Code sandbox for analysis scripts (architecture doc §9.1, §10).

A script runs as a child process with no network, a read-only view of the snapshot, write access
only to its output directory, and an empty environment so no credential of the parent leaks in.
On platforms without an isolation backend the sandbox refuses instead of running unprotected.
"""

import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from growbridge.ports import Denied

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
# Reads are denied by default; only what the interpreter needs to start is allowed back.
SYSTEM_READ = (
    "/usr/lib",
    "/usr/share",
    "/System",
    "/Library/Preferences/Logging",
    "/private/var/db/dyld",
    "/private/var/db/timezone",
    "/private/etc/localtime",
    "/dev",
)
BASE_PROFILE = """
(version 1)
(allow default)
(deny network*)
(deny signal)
(allow signal (target self))
(deny process-info* (target others))
(deny file-write*)
(allow file-write* (subpath (param "OUT")) (literal "/dev/null"))
(deny file-read*)
(allow file-read-metadata)
(allow file-read* (literal "/"))  ; the root listing is needed to start Python
"""


def build_profile(deny_read: Sequence[Path], allow_read: Sequence[Path]) -> tuple[str, list[str]]:
    """Profile text and ``-D`` definitions. Seatbelt applies the last matching rule: everything
    is denied first, then the system paths, then ``deny_read`` roots, then ``allow_read``."""
    lines = [BASE_PROFILE]
    definitions = []
    groups = (
        ("SYS", "allow", [Path(item) for item in SYSTEM_READ]),
        ("DENY", "deny", deny_read),
        ("ALLOW", "allow", allow_read),
    )
    for kind, verb, paths in groups:
        for index, path in enumerate(paths):
            name = f"{kind}{index}"
            definitions.append(f"{name}={path}")
            lines.append(f'({verb} file-read* (subpath (param "{name}")))')
            if verb == "deny":  # path resolution needs stat(), never the contents
                lines.append(f'(allow file-read-metadata (subpath (param "{name}")))')
    return "\n".join(lines), definitions


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


class Sandbox(Protocol):
    def run(
        self, script: Path, snapshot_dir: Path, out_dir: Path, timeout: float
    ) -> SandboxResult: ...


class RefusingSandbox:
    """Used where no isolation backend exists: nothing runs."""

    def run(self, script: Path, snapshot_dir: Path, out_dir: Path, timeout: float) -> SandboxResult:
        raise Denied(
            "sandbox_unavailable",
            "no isolation backend on this platform",
            reason="sandbox_unavailable",
            params={},
        )


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode(errors="replace") if isinstance(value, bytes) else value


def _package_manager_roots(binary: Path) -> list[Path]:
    """A Homebrew interpreter loads its dylibs from the Homebrew prefix (the dir above Cellar)."""
    return [parent.parent for parent in binary.parents if parent.name == "Cellar"]


class SeatbeltSandbox:
    """macOS ``sandbox-exec``. The script receives ``<snapshot_dir> <out_dir>`` as arguments.

    Reads under ``deny_read`` (default: the home directory) are refused except for the snapshot,
    the output directory, the script's directory and the interpreter's installation.
    """

    def __init__(self, deny_read: Sequence[Path] | None = None):
        roots = [Path.home()] if deny_read is None else list(deny_read)
        self.deny_read = tuple(root.resolve() for root in roots)

    def run(self, script: Path, snapshot_dir: Path, out_dir: Path, timeout: float) -> SandboxResult:
        snapshot = snapshot_dir.resolve()
        out = out_dir.resolve()
        script = script.resolve()
        real_python = Path(sys.executable).resolve()
        interpreter = {
            Path(sys.prefix).resolve(),
            Path(sys.base_prefix).resolve(),
            real_python.parents[1],  # installation that holds the real binary
            *_package_manager_roots(real_python),
        }
        allowed = [snapshot, out, script.parent, *sorted(interpreter)]
        profile, definitions = build_profile(self.deny_read, allowed)
        flags = [item for definition in definitions for item in ("-D", definition)]
        command = [
            SANDBOX_EXEC,
            "-D",
            f"OUT={out}",
            *flags,
            "-p",
            profile,
            sys.executable,
            "-I",
            str(script),
            str(snapshot),
            str(out),
        ]
        try:
            done = subprocess.run(
                command,
                env={},
                cwd=out,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as expired:
            return SandboxResult(-1, _text(expired.stdout), _text(expired.stderr), True)
        return SandboxResult(done.returncode, done.stdout, done.stderr, False)


def make_sandbox() -> Sandbox:
    if sys.platform == "darwin" and os.path.exists(SANDBOX_EXEC):
        return SeatbeltSandbox()
    return RefusingSandbox()
