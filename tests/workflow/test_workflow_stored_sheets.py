"""A run sheet an earlier version stored keeps loading after the input checks of the batch 3
follow-up (repeated row ids, a retained level outside its range): raw records are never
rewritten, so the stage it governs can still be read, approved and run."""

from growbridge.archive.models import STORED, RunSheet


def stored_before_the_checks(world) -> RunSheet:
    data = world.sheet().model_dump(mode="json")
    data["timed_actions"] = [data["timed_actions"][0], data["timed_actions"][0]]
    fan = next(plan for plan in data["channels"] if plan["channel"] == "fan")
    fan["retained_level"] = 40  # the fan stops at 10
    return RunSheet.model_validate(data, context=STORED)


async def test_a_stage_whose_stored_sheet_breaks_the_input_checks_reads_approves_and_runs(world):
    await world.design()
    sheet = stored_before_the_checks(world)
    world.svc.submit_run_sheet(world.round_id, sheet, world.op)  # as an earlier version did

    assert world.svc.stage("stage-1").run_sheet == sheet
    world.svc.approve("stage-1", world.op)
    await world.svc.start_stage("stage-1", world.op)
    assert world.state() == "running"
    assert world.svc.stage("stage-1").run_sheet.digest() == sheet.digest()
