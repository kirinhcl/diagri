import argparse
import asyncio
import contextlib
import fcntl
import getpass
import json
import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from . import __version__
from .config import default_config, initialize, load
from .logging_setup import configure_logging

ROLE_TOKEN_PREFIX = "GROWBRIDGE_ROLE_TOKEN_"
TICK_SECONDS = 1.0
AGENT_SECONDS = 30.0
log = logging.getLogger(__name__)


def role_tokens_from_env(environ: Mapping[str, str]) -> dict[str, str]:
    """Model-role tokens come only from ``GROWBRIDGE_ROLE_TOKEN_<ROLE>``; empty ones are ignored."""
    tokens = {}
    for key, value in environ.items():
        role = key.removeprefix(ROLE_TOKEN_PREFIX).lower()
        if key.startswith(ROLE_TOKEN_PREFIX) and role and value:
            tokens[role] = value
    return tokens


def _add_operator(parser, settings, name: str, admin: bool = False) -> None:
    from .archive.clock import SystemClock
    from .archive.db import Database
    from .runtime import private_dir
    from .workbench.auth import MIN_SECRET_LENGTH, Operators

    secret = getpass.getpass("Operator secret: ")
    if len(secret) < MIN_SECRET_LENGTH:
        parser.error(f"the secret needs at least {MIN_SECRET_LENGTH} characters")
    if getpass.getpass("Repeat secret: ") != secret:
        parser.error("the two entries differ")
    db = Database(private_dir(settings.data_dir) / "workflow.sqlite3")
    try:
        Operators(db, SystemClock()).add(name, secret, "admin" if admin else "user")
    except ValueError as error:
        parser.error(str(error))
    finally:
        db.close()
    print(f"Operator added: {name}")


def _register_host(parser, settings) -> None:
    from .ports import Denied
    from .runtime import register_write_host

    try:
        host_id = register_write_host(settings)
    except Denied as error:
        parser.error(str(error))
    print(f"Write host registered: {host_id}")


async def _bump_recovery(settings, reason: str) -> int:
    from .runtime import build_runtime

    runtime = build_runtime(settings)
    try:
        return await runtime.bump_recovery(reason)
    finally:
        await runtime.stop()


def _recovery_bump(parser, settings, reason: str) -> None:
    """Offline only: the daemon lock must be free, and it is held while the number changes."""
    from .runtime import private_dir

    with (private_dir(settings.data_dir) / "daemon.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("a daemon is running on this data directory; stop it first")
        number = asyncio.run(_bump_recovery(settings, reason))
    print(f"Recovery number is now {number}; confirm the safety config and review live stages")


async def _tick_forever(runtime) -> None:
    while True:
        await runtime.tick()  # every step guards itself; a failure becomes an alert
        await asyncio.sleep(TICK_SECONDS)


def model_client_or_none(runtime):
    """The Anthropic client, or ``None`` (with a warning and an alert) when it cannot be built.

    The SDK is an optional extra and credentials come from the environment, so failure is normal.
    """
    try:
        from .agents.llm import AnthropicClient

        return AnthropicClient()
    except Exception as error:
        log.warning("model roles are off: %s: %s", type(error).__name__, error)
        message = f"Model roles are off: {type(error).__name__}: {error}"
        runtime.alert("model_client", "anthropic", message, code="model_client")
        return None


async def _agents_forever(runtime, client) -> None:
    while True:
        await runtime.run_agents(client)  # a failing task becomes an alert, never an exception
        await asyncio.sleep(AGENT_SECONDS)


async def _serve_listeners(app, settings) -> None:
    """The loopback listener (behind the overlay proxy), plus the on-site listener when both
    ``lan_bind`` and ``lan_port`` are set. The entry of a request follows the listener that
    accepted it, so both serve the same app in this one event loop."""
    import uvicorn

    main = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=settings.port, log_level="info")
    )
    if not (settings.lan_bind and settings.lan_port):
        await main.serve()
        return
    lan = uvicorn.Server(
        uvicorn.Config(
            app, host=settings.lan_bind, port=settings.lan_port, log_level="info", lifespan="off"
        )
    )
    lan.capture_signals = contextlib.nullcontext  # the main server owns the signals
    lan_task = asyncio.create_task(lan.serve())
    try:
        await main.serve()
    finally:
        lan.should_exit = True
        await asyncio.gather(lan_task, return_exceptions=True)


async def _serve_auto_research(settings) -> None:
    from .api import create_app
    from .runtime import build_runtime
    from .runtime_compute import ComputeConfigError, compute_options, install_input_guard
    from .runtime_heartbeat import heartbeats_from_env

    try:  # one heartbeat URL without the other would watch only half of the failures
        heartbeats = heartbeats_from_env()
    except ValueError as error:
        raise SystemExit(f"growbridge: {error}") from error
    try:  # compute starts only when completely configured; a bad template stops the daemon
        compute = compute_options(settings, os.environ)
    except ComputeConfigError as error:
        raise SystemExit(f"growbridge: {error}") from error
    runtime = build_runtime(settings, heartbeats=heartbeats, **compute)
    install_input_guard(runtime)  # a model names inputs: only own-project snapshots may leave
    try:  # a too-short role token stops the daemon before anything starts
        router = runtime.workbench(role_tokens_from_env(os.environ))
    except ValueError as error:
        raise SystemExit(f"growbridge: {error}") from error
    await runtime.start()
    ticker = asyncio.create_task(_tick_forever(runtime))
    client = model_client_or_none(runtime) if settings.roles else None
    agents = None if client is None else asyncio.create_task(_agents_forever(runtime, client))
    app = create_app(settings, bridge=runtime.bridge, workbench=router)
    try:
        await _serve_listeners(app, settings)
    finally:
        background = [t for t in (ticker, agents) if t is not None]
        for background_task in background:
            background_task.cancel()
        await asyncio.gather(*background, return_exceptions=True)
        await runtime.stop()


def _export_dataset(settings, args) -> None:
    from .dataset.command import export_dataset
    from .dataset.source import ExportRefused

    try:
        summary = export_dataset(
            settings.data_dir,
            args.snapshot,
            args.out,
            args.licence.strip(),
            args.creator.strip(),
            (args.url or "").strip() or None,
            __version__,
        )
    except ExportRefused as refused:
        print(f"export refused: {refused}", file=sys.stderr)
        raise SystemExit(1) from None
    report = {"out": str(summary.out), "rows": dict(summary.rows), "counts": dict(summary.counts)}
    print(json.dumps(report, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    """The command line: global options and every subcommand (the wiki's CLI reference is
    checked against it)."""
    parser = argparse.ArgumentParser(description="Local Spider Farmer BLE service and MCP tools")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", type=Path, default=default_config())
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser(
        "init", help="Create private configuration without overwriting existing files"
    )
    init.add_argument(
        "--device", required=True, help="Address/UUID returned by scan on this machine"
    )
    init.add_argument("--enable-controls", action="store_true")
    sub.add_parser("scan", help="Scan nearby Spider Farmer devices")
    sub.add_parser("serve", help="Run the single-owner BLE service and loopback HTTP API")
    sub.add_parser("mcp", help="Run MCP over stdio; connects to the already-running daemon")
    sub.add_parser("status", help="Read current daemon state")
    dashboard = sub.add_parser(
        "dashboard", help="Open the local dashboard with a one-use connection link"
    )
    dashboard.add_argument(
        "--no-open",
        action="store_true",
        help="Print the short-lived link instead of opening a browser",
    )
    operator = sub.add_parser("operator", help="Manage workbench operators (auto_research)")
    operator_sub = operator.add_subparsers(dest="operator_command", required=True)
    add = operator_sub.add_parser(
        "add", help="Add an operator; the secret is asked for, not passed"
    )
    add.add_argument("name")
    add.add_argument("--admin", action="store_true", help="Make the operator an administrator")
    host = sub.add_parser("host", help="Manage the write host of this device (auto_research)")
    host_sub = host.add_subparsers(dest="host_command", required=True)
    host_sub.add_parser("register", help="Make this machine the registered write host")
    recovery = sub.add_parser("recovery", help="Recovery number after a restore or host change")
    recovery_sub = recovery.add_subparsers(dest="recovery_command", required=True)
    bump = recovery_sub.add_parser("bump", help="Raise the recovery number (daemon stopped)")
    bump.add_argument("--reason", required=True, help="Why: restore, host change, ...")
    export = sub.add_parser(
        "export-dataset", help="Write the training dataset of a frozen snapshot (read-only)"
    )
    export.add_argument("--snapshot", required=True, help="Snapshot id")
    export.add_argument("--out", required=True, type=Path, help="New directory to write")
    export.add_argument("--licence", required=True, help="Licence the dataset is released under")
    export.add_argument("--creator", required=True, help="Creator named in the metadata")
    export.add_argument("--url", help="Where the dataset is published, if anywhere")
    sub.add_parser("simulate", help="Run a short simulated stage (no radio, no network)")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    os.umask(0o077)
    if args.command == "init":
        initialize(args.config, args.device, args.enable_controls)
        print(f"Configuration created: {args.config}")
        return
    if args.command == "scan":
        from .transport import scan_devices

        data_dir = Path.home() / ".local" / "share" / "spiderfarmer-growbridge"
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        print(json.dumps(asyncio.run(scan_devices(data_dir)), ensure_ascii=False, indent=2))
        return
    if args.command == "simulate":
        from .runtime import simulate_stage

        print(json.dumps(asyncio.run(simulate_stage()), ensure_ascii=False, indent=2))
        return
    settings = load(args.config)
    if args.command == "export-dataset":
        _export_dataset(settings, args)
    elif args.command == "operator":
        _add_operator(parser, settings, args.name, args.admin)
    elif args.command == "host":
        _register_host(parser, settings)
    elif args.command == "recovery":
        _recovery_bump(parser, settings, args.reason)
    elif args.command == "dashboard":
        import webbrowser

        from .client import Client

        result = asyncio.run(Client(settings).call("POST", "/ui/session"))
        url = settings.url + "/#session=" + result["code"]
        if args.no_open:
            print(url)
        else:
            webbrowser.open(url)
            print("Dashboard opened. Connection link expires in 60 seconds.")
    elif args.command == "mcp":
        from .mcp_server import create_mcp

        create_mcp(settings).run(transport="stdio")
    elif args.command == "status":
        from .client import Client

        print(
            json.dumps(
                asyncio.run(Client(settings).call("GET", "/status")), ensure_ascii=False, indent=2
            )
        )
    elif args.command == "serve":
        import uvicorn

        from .api import create_app

        settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (settings.data_dir / "daemon.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                parser.error("A daemon already owns this data directory")
            configure_logging()  # also keeps httpx from logging request URLs (secrets)
            if settings.auto_research:
                asyncio.run(_serve_auto_research(settings))
                return
            uvicorn.run(
                create_app(settings), host="127.0.0.1", port=settings.port, log_level="info"
            )


if __name__ == "__main__":
    main()
