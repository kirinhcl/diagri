from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from growbridge.archive.db import Database
from growbridge.archive.models import SampleRecord
from growbridge.sim.clock import FakeClock

TZ = "Europe/Helsinki"
DAY = date(2026, 11, 10)
DAY_START = datetime(2026, 11, 10, tzinfo=ZoneInfo(TZ)).timestamp()


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "observer.db")
    yield database
    database.close()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def make_sample():
    counter = iter(range(10_000))

    def build(offset: float, data: dict, **fields) -> SampleRecord:
        at = DAY_START + offset
        values = {
            "id": f"s{next(counter)}",
            "experiment_id": "e1",
            "stage_id": "st1",
            "device_id": "ac5",
            "captured_at": at,
            "received_at": at,
            "clock_synced": True,
            "data": data,
        }
        values.update(fields)
        return SampleRecord(**values)

    return build
