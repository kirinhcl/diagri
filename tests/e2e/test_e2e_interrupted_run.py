"""A process that died during an analysis run: the next start settles the run as failed."""

from growbridge.research.analysis import ConfirmatoryRunner
from growbridge.sim.fixtures import make_protocol

SCRIPT = b"print('frozen analysis')\n"


async def test_starting_the_runtime_settles_a_run_the_last_process_left_unfinished(world):
    first = await world.boot()
    protocol = make_protocol()
    runner: ConfirmatoryRunner = first.runner
    runner.freeze_analysis(protocol, SCRIPT, "alice")
    first.runner.db.execute(
        "INSERT INTO research_runs(id, protocol_id, protocol_version, snapshot_id, "
        "script_sha256, started_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("run-live", protocol.id, protocol.version, "snap-1", "a" * 64, world.clock.now()),
    )
    assert runner.status("snap-1", protocol) == "running"
    await first.stop()  # the process ends with the run still open

    second = await world.boot()  # the restart

    assert second.runner.status("snap-1", protocol) == "failed"
    row = second.runner.db.one("SELECT interrupted FROM research_runs WHERE id = 'run-live'")
    assert row["interrupted"] == 1
