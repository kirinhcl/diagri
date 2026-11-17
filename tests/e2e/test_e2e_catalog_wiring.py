"""The runtime loads the variable catalog once, at startup, and shares that one instance."""

import pytest

from growbridge.vocab import CatalogError, packaged_catalog


async def test_runtime_shares_one_catalog(world):
    runtime = await world.boot()

    assert runtime.workflow.catalog is packaged_catalog()
    assert runtime.holdout.catalog is packaged_catalog()


async def test_runtime_refuses_to_start_with_a_broken_catalog(world, monkeypatch):
    monkeypatch.setattr("growbridge.vocab.catalog.packaged_text", lambda: "version = [")
    packaged_catalog.cache_clear()
    try:
        with pytest.raises(CatalogError):
            await world.boot()
    finally:
        monkeypatch.undo()
        packaged_catalog.cache_clear()
