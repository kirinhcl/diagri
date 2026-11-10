from growbridge.archive.models import Channel, RuleAction
from growbridge.executor.rules import RuleState, evaluate_protection
from growbridge.ports import Reading
from growbridge.sim.fixtures import make_safety

GAP = 120.0


def reading(value, mono, *, quality="ok", unit="C"):
    return Reading(sensor="temp", value=value, unit=unit, at=mono, mono=mono, quality=quality)


def run(rule, samples, state=None):
    state = state or RuleState()
    out = []
    for value, mono in samples:
        decision = evaluate_protection(rule, reading(value, mono), state, mono, GAP)
        state = decision.state
        out.append((mono, decision))
    return out


def hot(start, stop, value=40.0):
    return [(value, float(t)) for t in range(start, stop + 1)]


def test_protection_fires_after_duration_and_keeps_acting_while_condition_holds():
    rule = make_safety().rules[0]
    result = run(rule, hot(0, 40))
    fired = [mono for mono, d in result if d.action is not None]
    assert fired[0] == 30.0
    assert fired[-1] == 40.0
    assert result[30][1].action == RuleAction(channel=Channel.LIGHT, level=0)
    assert result[30][1].state.active is True


def test_protection_does_not_fire_before_duration():
    rule = make_safety().rules[0]
    assert all(d.action is None for _, d in run(rule, hot(0, 29)))


def test_protection_clears_when_condition_stops_holding():
    rule = make_safety().rules[0]
    result = run(rule, hot(0, 35) + [(30.0, 36.0)])
    assert result[-1][1].action is None
    assert result[-1][1].state.active is False


def test_protection_invalid_reading_takes_no_action():
    rule = make_safety().rules[0]
    for bad in (
        None,
        reading(None, 0),
        reading(40, 0, quality="suspect"),
        reading(40, 0, unit="%"),
    ):
        decision = evaluate_protection(rule, bad, RuleState(), 5.0, GAP)
        assert decision.action is None
        assert decision.pause is False


def test_protection_stale_reading_cannot_keep_firing():
    rule = make_safety().rules[0]
    state = run(rule, hot(0, 35))[-1][1].state
    decision = evaluate_protection(rule, reading(40, 35), state, 100.0, GAP)
    assert decision.action is None
    assert decision.state.since is None


def test_rules_protection_gap_breaks_continuity():
    rule = make_safety().rules[0]
    # validity is 20 s, so keep readings fresh but leave a 150 s hole in the stream
    state = run(rule, hot(0, 20))[-1][1].state
    decision = evaluate_protection(rule, reading(40, 170), state, 170.0, GAP)
    assert decision.action is None
    assert decision.state.since == 170.0


def test_protection_ignores_wall_clock():
    rule = make_safety().rules[0]
    state = RuleState()
    fired = []
    for mono in range(0, 31):
        sample = Reading(
            sensor="temp", value=40.0, unit="C", at=1e9 - 7200 * (mono > 10), mono=float(mono)
        )
        decision = evaluate_protection(rule, sample, state, float(mono), GAP)
        state = decision.state
        if decision.action is not None:
            fired.append(mono)
    assert fired == [30]
