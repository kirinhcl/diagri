"""Demo launcher: run scripts/dev_workbench.py unchanged, with sign-in sessions that last.

Under --fast-forward the development clock jumps ~28 steps of 300 s per real second, so an
8-hour workbench session expires within seconds and the recorded browser would be thrown back
to the login page mid-stage. This launcher only raises growbridge.workbench.auth.SESSION_SECONDS
(read at login time) before handing over to the harness's own main(), which takes the same
arguments. Re-authentication (REAUTH_SECONDS) is untouched. With DEMO_CLEAN_SEED=1 a fresh data
directory gets the approved safety limits but no seeded project, so the inbox starts clean.
"""

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # scripts/demo/ -> the repository root
DEMO_SESSION_SECONDS = 10 * 365 * 24 * 3600  # outlives any fast-forwarded stage

sys.path.insert(0, str(REPO / "scripts"))

import growbridge.workbench.auth as auth  # noqa: E402

auth.SESSION_SECONDS = DEMO_SESSION_SECONDS

import dev_workbench  # noqa: E402


def _seed_safety_only(runtime) -> None:
    """Approve the fixture safety limits but create no project, so the demo starts clean."""
    from growbridge.sim.fixtures import make_safety

    runtime.control.approve_safety(make_safety(), dev_workbench.OPERATOR)


if os.environ.get("DEMO_CLEAN_SEED") == "1":
    dev_workbench._seed = _seed_safety_only  # prepare() looks _seed up at call time

if __name__ == "__main__":
    sys.exit(dev_workbench.main())
