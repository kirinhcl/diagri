"""With no current stage the executor holds the device at its idle levels (design 2026-11-24)."""

from growbridge.archive.models import Channel, RightKind, RuleAction
from growbridge.sim.fixtures import make_safety

LIGHT, EXHAUST, FAN = Channel.LIGHT, Channel.EXHAUST, Channel.FAN
IDLE = (
    RuleAction(channel=LIGHT, level=20),
    RuleAction(channel=EXHAUST, level=10),
    RuleAction(channel=FAN, level=0),
)


async def idle_rig(make_rig, levels=IDLE):
    rig = await make_rig(idle_levels=levels)
    await rig.svc.restore_care()  # what the runtime does every tick
    return rig


async def shown(rig) -> tuple[int, int, int]:
    levels = await rig.levels()
    return levels[LIGHT], levels[EXHAUST], levels[FAN]


def idle_records(rig):
    return [r for r in rig.sink.actions if r.trigger.startswith("idle:")]


async def test_idle_levels_reach_the_device_when_no_stage_exists(make_rig):
    rig = await idle_rig(make_rig)

    await rig.tick()

    assert await shown(rig) == (20, 10, 0)
    records = idle_records(rig)
    assert {r.trigger for r in records} >= {"idle:light", "idle:exhaust"}
    assert all(r.experiment_id is None and r.stage_id is None for r in records)


async def test_idle_writes_once_per_phase(make_rig):
    rig = await idle_rig(make_rig)
    await rig.tick()
    sent = len(rig.writes())

    await rig.pass_time(5)
    await rig.tick()

    assert len(rig.writes()) == sent


async def test_idle_never_touches_the_pump(make_rig):
    rig = await idle_rig(make_rig)

    await rig.tick()

    assert all(key != "outlet" or "pump" not in key for key, _ in rig.written())
    assert not [r for r in idle_records(rig) if r.channel is Channel.PUMP]


async def test_idle_skips_a_channel_protection_holds(make_rig):
    rig = await idle_rig(make_rig)
    rig.control.approve_safety(make_safety(), "op-1")
    rig.sim.set_sensor("temp", 40)  # the fixture rule switches the light off above 35 C
    await rig.pass_time(1)
    await rig.tick()
    await rig.pass_time(31)

    await rig.tick()
    await rig.tick()

    assert (await rig.levels())[LIGHT] == 0
    assert (await rig.levels())[EXHAUST] == 10


async def test_idle_waits_for_the_link(make_rig, monkeypatch):
    rig = await idle_rig(make_rig)
    monkeypatch.setattr(rig.control, "connected", lambda: False)

    await rig.tick()

    assert idle_records(rig) == []
    monkeypatch.undo()
    await rig.tick()
    assert await shown(rig) == (20, 10, 0)


async def test_idle_realigns_under_a_new_right(make_rig):
    rig = await idle_rig(make_rig)
    await rig.tick()
    rig.sim.external_change("device", "light", mLevel=50)
    await rig.refresh()
    await rig.tick()
    assert (await rig.levels())[LIGHT] == 50  # within one right, a change by hand stays

    await rig.control.startup()  # a restart revokes every right
    await rig.svc.restore_care()
    await rig.tick()

    assert (await rig.levels())[LIGHT] == 20


async def test_no_idle_while_a_stage_is_current(make_rig):
    rig = await idle_rig(make_rig)
    await rig.start()

    await rig.tick()

    assert idle_records(rig) == []
    assert (await rig.levels())[LIGHT] == 60  # the run sheet's level, not the idle one


async def test_nothing_without_idle_levels(make_rig):
    rig = await idle_rig(make_rig, levels=())

    await rig.tick()

    assert rig.writes() == []
    assert (
        rig.control.ledger.active_rights(
            rig.control.device_id, rig.control.recovery_number(), RightKind.CARE
        )
        == []
    )
