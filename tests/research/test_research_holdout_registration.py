"""Registering a holdout: explicit development batches, who registered it, and the rule that
matters most: a holdout may only be registered before any of its outcome data exists, because
data that already exists may have been seen (the same idea as freezing before the data)."""

import pytest
from vocab_support import TEST_CATALOG

from growbridge.archive.db import Database
from growbridge.ports import Denied
from growbridge.research.holdout import STEPS, HoldoutRegistry, project_outcomes
from growbridge.sim.clock import FakeClock

OUTCOMES = ("yield_g", "canopy_score")
DEV = ("dev-1", "dev-2")


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "holdout.db")
    yield database
    database.close()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def registry(db, clock):
    return HoldoutRegistry(db, clock, catalog=TEST_CATALOG)


# --- what is stored ----------------------------------------------------------------------------


def test_the_registration_keeps_development_batches_and_who_registered(registry, clock):
    registry.register("p1", "h1", ("b3",), OUTCOMES, DEV, registered_by="alice")

    (stored,) = registry.holdouts("p1")

    assert stored.holdout_id == "h1" and stored.project_id == "p1"
    assert stored.batch_ids == ("b3",) and stored.outcome_fields == OUTCOMES
    assert stored.development_batch_ids == DEV
    assert stored.registered_by == "alice" and stored.registered_at == clock.now()


def test_holdouts_are_listed_per_project_in_the_order_registered(registry):
    registry.register("p1", "h1", ("b3",), OUTCOMES, DEV)
    registry.register("p2", "h2", ("b4",), OUTCOMES, DEV)
    registry.register("p1", "h3", ("b5",), OUTCOMES, DEV)

    assert [h.holdout_id for h in registry.holdouts("p1")] == ["h1", "h3"]
    assert registry.holdouts("nobody") == ()


def test_a_registration_from_before_these_columns_has_no_development_batches(tmp_path, clock):
    database = Database(tmp_path / "old.db")
    database.migrate("research_holdout", STEPS[:4])  # the schema before the entry existed
    database.execute(
        "INSERT INTO holdouts VALUES (?, ?, ?, ?, ?)",
        ("h-old", "p1", '["b3"]', '["yield_g"]', 1.0),
    )
    try:
        (stored,) = HoldoutRegistry(database, clock, catalog=TEST_CATALOG).holdouts("p1")

        assert stored.development_batch_ids is None and stored.registered_by is None
        assert stored.batch_ids == ("b3",)
    finally:
        database.close()


# --- what is refused ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("held", "development"),
    [
        (("b3",), ("dev-1",)),  # fewer than two development batches
        (("b3",), ()),
        ((), DEV),  # nothing held out
        (("b3",), ("dev-1", "b3")),  # a batch on both sides
        (("b3", "b3"), DEV),  # repeated
        (("b3",), ("dev-1", "dev-1")),
        (("",), DEV),  # empty names
        (("b3",), ("dev-1", "")),
    ],
    ids=["one-dev", "no-dev", "no-holdout", "overlap", "dup-held", "dup-dev", "empty-h", "empty-d"],
)
def test_batch_lists_that_do_not_make_a_holdout_are_refused(registry, held, development):
    with pytest.raises(Denied) as caught:
        registry.register("p1", "h1", held, OUTCOMES, development)

    assert caught.value.code == "batches"
    assert registry.holdouts("p1") == ()


@pytest.mark.parametrize("fields", [(), ("",), ("yield_g", "yield_g"), ("yield_g", "")])
def test_outcome_fields_must_be_named_and_not_repeated(registry, fields):
    with pytest.raises(Denied) as caught:
        registry.register("p1", "h1", ("b3",), fields, DEV)

    assert caught.value.code == "param"
    assert registry.holdouts("p1") == ()


def test_registering_the_same_id_twice_is_still_refused(registry):
    registry.register("p1", "h1", ("b3",), OUTCOMES, DEV)

    with pytest.raises(Denied) as caught:
        registry.register("p1", "h1", ("b4",), OUTCOMES, DEV)

    assert caught.value.code == "state"


# --- the rule that matters most: before any outcome data exists --------------------------------


class Source:
    def __init__(self, answer: bool):
        self.answer, self.calls = answer, []

    def existing_outcomes(self, project_id, batch_ids, outcome_fields) -> tuple[str, ...]:
        self.calls.append((project_id, tuple(batch_ids), tuple(outcome_fields)))
        return ("yield_g",) if self.answer else ()


def test_a_holdout_whose_outcome_data_already_exists_is_refused(db, clock):
    source = Source(True)
    registry = HoldoutRegistry(db, clock, source, TEST_CATALOG)

    with pytest.raises(Denied) as caught:
        registry.register("p1", "h1", ("b3",), OUTCOMES, DEV)

    assert caught.value.code == "state"
    assert "may already have been seen" in str(caught.value)
    assert source.calls == [("p1", ("b3",), OUTCOMES)]
    assert registry.holdouts("p1") == ()


def test_without_outcome_data_the_registration_goes_through(db, clock):
    registry = HoldoutRegistry(db, clock, Source(False), TEST_CATALOG)

    registry.register("p1", "h1", ("b3",), OUTCOMES, DEV)

    assert [h.holdout_id for h in registry.holdouts("p1")] == ["h1"]


def project_source(matching: tuple, owners: dict):
    """``matching``: the experiments that hold a matching outcome; ``owners``: experiment -> the
    projects whose stages run it (missing or empty: no stage owns it)."""
    pairs = tuple((e, "yield_g") for e in matching)
    return project_outcomes(lambda batches: pairs, lambda e: owners.get(e, ()), TEST_CATALOG)


def test_a_matching_outcome_in_an_experiment_of_the_project_counts():
    source = project_source(("exp-2",), {"exp-2": ("p1",)})

    assert source.existing_outcomes("p1", ("b3",), OUTCOMES) != ()


def test_a_matching_outcome_in_another_projects_experiment_does_not_count():
    source = project_source(("exp-9",), {"exp-9": ("p2",)})

    assert source.existing_outcomes("p1", ("b3",), OUTCOMES) == ()
    assert source.existing_outcomes("p2", ("b3",), OUTCOMES) != ()


def test_a_matching_outcome_in_an_experiment_no_stage_owns_counts_for_every_project():
    """It cannot be shown to belong to another project, so it may belong to this one."""
    source = project_source(("exp-orphan",), {})

    assert source.existing_outcomes("p1", ("b3",), OUTCOMES) != ()
    assert source.existing_outcomes("p2", ("b3",), OUTCOMES) != ()


def test_an_experiment_shared_by_two_projects_counts_for_both():
    source = project_source(("exp-1",), {"exp-1": ("p1", "p2")})

    assert source.existing_outcomes("p2", ("b3",), OUTCOMES) != ()


def test_nothing_matching_means_no_outcomes():
    assert project_source((), {}).existing_outcomes("p1", ("b3",), OUTCOMES) == ()


def test_the_source_is_asked_with_the_batches_of_the_registration():
    asked = []
    source = project_outcomes(lambda b: asked.append(tuple(b)) or (), lambda e: (), TEST_CATALOG)

    source.existing_outcomes("p1", ("b3",), OUTCOMES)

    assert asked == [("b3",)]


def test_unresolved_existing_name_counts_as_an_outcome():
    source = project_outcomes(lambda b: [("exp-1", "yeild_g")], lambda e: ("p1",), TEST_CATALOG)
    assert source.existing_outcomes("p1", ("b3",), ("yield_g",)) == ("yeild_g",)


def test_outcome_fields_must_resolve(db, clock):
    registry = HoldoutRegistry(db, clock, catalog=TEST_CATALOG)
    with pytest.raises(Denied, match="yeild_g") as refused:
        registry.register("p1", "h1", ["b3"], ["yeild_g"], DEV)
    assert refused.value.code == "param"


def test_refusal_lists_the_names_that_block_registration(db, clock):
    source = project_outcomes(lambda b: [("exp-1", "yeild_g")], lambda e: ("p1",), TEST_CATALOG)
    registry = HoldoutRegistry(db, clock, source, TEST_CATALOG)
    with pytest.raises(Denied, match="yeild_g"):
        registry.register("p1", "h1", ["b3"], ["yield_g"], DEV)
