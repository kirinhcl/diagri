"""Run the workbench on the simulated AC5 for development: no radio, no network, no real device.

    GROWBRIDGE_DEV_SECRET='<at least 12 characters>' .venv/bin/python scripts/dev_workbench.py

The operator ``dev`` signs in with that secret at http://localhost:8770/workbench. A fresh data
directory gets one approved safety limit set and one stage waiting for review; a reused
``--data-dir`` (one that already holds databases) is opened as it is, without seeding or approving.

``--roles FILE.toml`` also runs the model roles, as ``serve`` does when ``roles`` is configured.
The file holds one ``[orchestrator]``, ``[planner]`` or ``[researcher]`` table per role with the
fields of ``RoleModel``. The Anthropic SDK reads its endpoint and key from the environment, so a
local Anthropic-compatible server (Ollama, say) is reached with ``ANTHROPIC_BASE_URL``.
``--claude-code`` runs the roles on the local Claude Code CLI (``claude -p``, see
``claude_code_client.py``) instead of the Anthropic SDK: no API key, the account Claude Code is
signed in with. Without ``--roles`` all three roles then run the default model.
``--fast-forward`` skips through a running stage: while a stage runs, each step moves the clock on
by one sampling interval of its run sheet, asks the simulated device for a reading and ticks, so a
week-long stage takes minutes and its data stay complete. Outside a running stage time is real.
The skipped time is kept in ``dev_clock_offset`` in the data directory, so a restart never sends
the clock back. Sessions and re-authentication age with that clock: sign in again afterwards.
The simulated sensors follow a small tent model (``Greenhouse``): day and night, the light and
the exhaust move temperature, humidity and CO2, with noise, so no reading looks frozen.
``--trace`` records every model-role run as a JSONL trace under ``<data-dir>/model_traces`` and
copies the data directory before each run, so ``growbridge trace replay`` can run it again exactly.
It needs ``--data-dir``, holds prompts and tool results in clear text and is for development only.
"""

import argparse
import asyncio
import os
import secrets
import sys
import tempfile
import time
import tomllib
from pathlib import Path

DEV_PORT = 8765
DEV_LAN_PORT = 8770
SECRET_VARIABLE = "GROWBRIDGE_DEV_SECRET"
OPERATOR = "dev"
STAGE_ID = "stage-dev"
STATUS_SECONDS = 1.0  # a real AC5 pushes telemetry; the simulator answers only when asked
TICK_SECONDS = 1.0
FAST_PAUSE_SECONDS = 0.01  # between fast-forward steps, so the workbench keeps answering
MAX_FAST_STEP_SECONDS = 600.0
OFFSET_FILE = "dev_clock_offset"


class OffsetClock:
    """Real time plus a skipped amount that only grows; ``advance`` skips ahead."""

    def __init__(self, path: Path | None = None, synced: bool = True):
        self.synced = synced
        self.path = path
        self.offset = 0.0
        if path is not None and path.exists():
            self.offset = float(path.read_text().strip() or 0)

    def now(self) -> float:
        return time.time() + self.offset

    def monotonic(self) -> float:
        return time.monotonic() + self.offset

    def advance(self, seconds: float) -> None:
        self.offset += max(0.0, seconds)
        if self.path is not None:
            self.path.write_text(repr(self.offset))


def fast_step(runtime) -> float | None:
    """Seconds to skip now: one sampling interval of the running stage, or None (real time)."""
    from growbridge.workflow.states import StageState

    stage = runtime.workflow.store.active()
    if stage is None or stage.state is not StageState.RUNNING:
        return None
    sheet = runtime.workflow.store.run_sheet(stage.run_sheet_id, stage.run_sheet_version)
    return min(sheet.sampling.interval_seconds, MAX_FAST_STEP_SECONDS)


class Greenhouse:
    """A small grow tent around the simulated AC5, so its sensors move as real ones do.

    The simulator's sensors are constant, and a reading that never changes is what the
    frozen-reading check pauses a stage for. Here the air warms by day and under the light, the
    exhaust cools and dries it, the canopy draws CO2 down while the light is on, and every
    reading carries a little noise. ``update(sim, now)`` sets the readings for UTC time ``now``.
    """

    def __init__(self, seed: int = 20261114):
        import random

        self.random = random.Random(seed)

    @staticmethod
    def _level(sim, module: str) -> float:
        block = sim.config["device"][module]
        return float(block["mLevel"]) if block["mOnOff"] else 0.0

    def update(self, sim, now: float) -> None:
        import math

        day = math.sin(2 * math.pi * ((now % 86400) / 86400 - 0.375))  # warmest mid-afternoon
        light, exhaust = self._level(sim, "light"), self._level(sim, "blower")
        noise = self.random.gauss
        temp = 20.5 + 1.5 * day + 0.045 * light - 0.02 * exhaust + noise(0, 0.12)
        humi = 64 - 1.6 * (temp - 21) - 0.06 * exhaust + noise(0, 0.5)
        co2 = 560 - 1.4 * light + 0.5 * exhaust + noise(0, 6)
        sim.set_sensor("temp", round(temp, 1))
        sim.set_sensor("humi", round(min(95.0, max(20.0, humi)), 1))
        sim.set_sensor("co2", round(max(380.0, co2)))


async def tick_forever(runtime, clock: OffsetClock | None, sleep=asyncio.sleep, vary=None) -> None:
    """Tick once a second; with a fast-forward clock, step through a running stage instead.
    ``vary(now)``, when given, moves the simulated readings on before each step."""
    while True:
        step = fast_step(runtime) if clock is not None else None
        if vary is not None:
            vary(runtime.clock.now() + (step or 0))
        if step is not None:
            clock.advance(step)
            try:
                await runtime.bridge.request("getDevSta")
            except Exception as error:  # noqa: BLE001 - one missed reading is a gap, not a crash
                print(f"status request failed: {type(error).__name__}", file=sys.stderr)
        await runtime.tick()  # every step guards itself; a failure becomes an alert
        await sleep(FAST_PAUSE_SECONDS if step is not None else TICK_SECONDS)


def _seed(runtime) -> None:
    """Approve the safety limits and leave one run sheet in ``pending_review``."""
    from growbridge.ports import Actor
    from growbridge.sim.fixtures import make_protocol, make_safety, treated_run_sheet

    flow = runtime.workflow
    operator = Actor(kind="operator", id=OPERATOR, reauth_at=runtime.clock.now())
    runtime.control.approve_safety(make_safety(), operator.id)
    project = flow.create_project("dev light stage", operator)
    protocol = make_protocol(project_id=project)
    flow.save_protocol(protocol, operator)
    round_id = flow.create_round(project, protocol.id, operator)
    sheet = treated_run_sheet(  # the workflow requires round 1's treatment
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


def is_fresh(data_dir: Path) -> bool:
    """True when no database of an earlier run is there: only then is anything seeded."""
    return not any(data_dir.glob("*.sqlite3"))


def prepare(runtime, secret: str, fresh: bool) -> None:
    """A fresh data directory gets the operator, the fixture safety limits and one stage to review.
    A reused one is left as it is: the fixture limits are never approved over what is there."""
    if fresh:
        runtime.operators.add(OPERATOR, secret)
    runtime.control.register_host()
    if fresh:
        _seed(runtime)
        return
    print(
        f"Reusing the data in {runtime.settings.data_dir}: nothing seeded, no safety limits "
        f"approved, no operator added (sign in as before).",
        file=sys.stderr,
    )


async def poll_status(request, interval: float = STATUS_SECONDS, sleep=asyncio.sleep) -> None:
    """Ask the device for its status forever so readings stay fresh; a failed ask is retried."""
    while True:
        try:
            await request("getDevSta")
        except Exception as error:  # noqa: BLE001 - a dev loop must outlive a busy device
            print(f"status request failed: {type(error).__name__}", file=sys.stderr)
        await sleep(interval)


def load_roles(path: Path) -> dict:
    """The ``RoleModel`` of each table in a roles file; a bad field fails here, before startup."""
    from growbridge.config import RoleModel

    tables = tomllib.loads(path.read_text())
    return {name: RoleModel(**table) for name, table in tables.items()}


ROLE_NAMES = ("orchestrator", "planner", "researcher")


def claude_code_client():
    """The Claude Code client of the file next to this script (scripts/ is not a package)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from claude_code_client import ClaudeCodeClient

    return ClaudeCodeClient()


async def _run(
    settings,
    secret: str,
    trace: bool = False,
    claude_code: bool = False,
    fast_forward: bool = False,
) -> None:
    from growbridge.api import create_app
    from growbridge.cli import (
        _agents_forever,
        _serve_listeners,
        model_client_or_none,
    )
    from growbridge.runtime import build_runtime
    from growbridge.sim.device import SimulatedTransport

    fresh = is_fresh(settings.data_dir)  # decided before build_runtime creates the databases
    clock = None
    if fast_forward:
        settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        clock = OffsetClock(settings.data_dir / OFFSET_FILE)
    sim = SimulatedTransport()
    greenhouse = Greenhouse()
    runtime = build_runtime(settings, lambda _: sim, clock, channels={})
    runtime.pre_run_copies = trace  # only this script may set it: never serve, never the config
    try:
        prepare(runtime, secret, fresh)
        router = runtime.workbench({})
        await runtime.start()
        vary = lambda now: greenhouse.update(sim, now)  # noqa: E731
        ticker = asyncio.create_task(tick_forever(runtime, clock, vary=vary))
        if clock is not None:
            print(f"Fast-forward: on (skipped so far: {clock.offset:.0f} s)")
        poller = asyncio.create_task(poll_status(runtime.bridge.request))
        if not settings.roles:
            client = None
        elif claude_code:
            client = claude_code_client()
            print("Model client: Claude Code CLI (claude -p)")
        else:
            client = model_client_or_none(runtime)
        if trace:
            print(f"Model traces: {settings.data_dir / 'model_traces'}")
        agents = None if client is None else asyncio.create_task(_agents_forever(runtime, client))
        if settings.roles:
            state = "on" if agents else "off (see the model_client alert)"
            print(f"Model roles: {state}: {', '.join(sorted(settings.roles))}")
        app = create_app(settings, bridge=runtime.bridge, workbench=router)
        print(f"On-site entry: http://localhost:{DEV_LAN_PORT}/workbench  (operator: {OPERATOR})")
        print(f"Overlay entry: http://127.0.0.1:{DEV_PORT}/workbench")
        try:
            await _serve_listeners(app, settings)
        finally:
            background = [t for t in (ticker, poller, agents) if t is not None]
            for task in background:
                task.cancel()
            await asyncio.gather(*background, return_exceptions=True)
    finally:
        await runtime.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, help="default: a fresh temporary directory")
    parser.add_argument("--roles", type=Path, help="TOML file of model roles; default: none run")
    parser.add_argument(
        "--trace", action="store_true", help="record each model run, with a pre-run data copy"
    )
    parser.add_argument(
        "--claude-code", action="store_true", help="run the roles on the local claude CLI"
    )
    parser.add_argument("--fast-forward", action="store_true", help="skip through a running stage")
    args = parser.parse_args()
    if args.trace and args.data_dir is None:
        print(
            "--trace needs --data-dir: the traces and pre-run copies must outlive the workbench",
            file=sys.stderr,
        )
        return 2
    secret = os.environ.get(SECRET_VARIABLE, "")
    if len(secret) < 12:
        print(f"{SECRET_VARIABLE} must be set to at least 12 characters", file=sys.stderr)
        return 2
    from growbridge.config import RoleModel, Settings

    try:
        roles = load_roles(args.roles) if args.roles else {}
        if args.claude_code and not roles:
            roles = {name: RoleModel() for name in ROLE_NAMES}
    except (OSError, tomllib.TOMLDecodeError, ValueError) as error:
        print(f"--roles {args.roles}: {error}", file=sys.stderr)
        return 2
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
            overlay_hosts=["127.0.0.1"],
            roles=roles,
            model_trace=args.trace,
        )
        try:
            asyncio.run(_run(settings, secret, args.trace, args.claude_code, args.fast_forward))
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
