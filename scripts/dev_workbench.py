"""Run the workbench on the simulated AC5 for development: no radio, no network, no real device.

    GROWBRIDGE_DEV_SECRET='<at least 12 characters>' .venv/bin/python scripts/dev_workbench.py

The operator ``dev`` signs in with that secret at http://localhost:8770/workbench. The data
holds one approved safety limit set and one stage waiting for review.
"""

import argparse
import asyncio
import os
import secrets
import sys
import tempfile
from pathlib import Path

DEV_PORT = 8765
DEV_LAN_PORT = 8770
SECRET_VARIABLE = "GROWBRIDGE_DEV_SECRET"
OPERATOR = "dev"
STAGE_ID = "stage-dev"


def _seed(runtime) -> None:
    """Approve the safety limits and leave one run sheet in ``pending_review``."""
    from growbridge.ports import Actor
    from growbridge.sim.fixtures import make_protocol, make_run_sheet, make_safety

    flow = runtime.workflow
    operator = Actor(kind="operator", id=OPERATOR, reauth_at=runtime.clock.now())
    runtime.control.approve_safety(make_safety(), operator.id)
    project = flow.create_project("dev light stage", operator)
    protocol = make_protocol(project_id=project)
    flow.save_protocol(protocol, operator)
    round_id = flow.create_round(project, protocol.id, operator)
    sheet = make_run_sheet(
        id="sheet-dev",
        project_id=project,
        experiment_id="experiment-dev",
        stage_id=STAGE_ID,
        protocol_id=protocol.id,
        protocol_version=protocol.version,
    )
    findings = flow.submit_run_sheet(round_id, sheet, Actor(kind="model", id="planner"))
    blocking = [item.message for item in findings if item.blocking]
    if blocking:
        raise RuntimeError("the dev run sheet was refused: " + "; ".join(blocking))


async def _run(settings, secret: str) -> None:
    from growbridge.api import create_app
    from growbridge.cli import _serve_listeners, _tick_forever
    from growbridge.runtime import build_runtime
    from growbridge.sim.device import SimulatedTransport

    runtime = build_runtime(settings, lambda _: SimulatedTransport(), channels={})
    try:
        runtime.operators.add(OPERATOR, secret)
        runtime.control.register_host()
        _seed(runtime)
        router = runtime.workbench({})
        await runtime.start()
        ticker = asyncio.create_task(_tick_forever(runtime))
        app = create_app(settings, bridge=runtime.bridge, workbench=router)
        print(f"Workbench: http://localhost:{DEV_LAN_PORT}/workbench  (operator: {OPERATOR})")
        try:
            await _serve_listeners(app, settings)
        finally:
            ticker.cancel()
            await asyncio.gather(ticker, return_exceptions=True)
    finally:
        await runtime.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, help="default: a fresh temporary directory")
    args = parser.parse_args()
    secret = os.environ.get(SECRET_VARIABLE, "")
    if len(secret) < 12:
        print(f"{SECRET_VARIABLE} must be set to at least 12 characters", file=sys.stderr)
        return 2
    from growbridge.config import Settings

    with tempfile.TemporaryDirectory() as scratch:
        settings = Settings(
            device="SIMULATED",
            token=secrets.token_urlsafe(32),
            data_dir=args.data_dir or Path(scratch) / "data",
            controls_enabled=True,
            pump_cooldown_seconds=0,
            auto_research=True,
            port=DEV_PORT,
            lan_bind="127.0.0.1",
            lan_port=DEV_LAN_PORT,
            lan_hosts=["localhost"],
        )
        try:
            asyncio.run(_run(settings, secret))
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
