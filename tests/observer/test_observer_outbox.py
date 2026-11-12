import logging

import pytest

from growbridge.observer.outbox import Outbox

BASE = 10.0
CAP = 40.0


class FakeChannel:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.sent: list[str] = []

    async def send(self, text):
        self.sent.append(text)
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def outbox(db, clock):
    return Outbox(db, clock, base_seconds=BASE, cap_seconds=CAP)


def test_queue_is_idempotent_per_event_and_channel(outbox):
    assert outbox.queue_notification("e1", "telegram", "hot") is True
    assert outbox.queue_notification("e1", "telegram", "hot again") is False
    assert outbox.queue_notification("e1", "email", "hot") is True
    assert outbox.queue_notification("e2", "telegram", "cold") is True


async def test_accepted_notification_is_not_sent_twice(outbox):
    channel = FakeChannel("accepted")
    outbox.queue_notification("e1", "telegram", "hot")

    assert await outbox.deliver({"telegram": channel}) == 1
    assert await outbox.deliver({"telegram": channel}) == 0

    assert channel.sent == ["hot"]
    assert outbox.status("e1", "telegram") == "accepted"
    assert outbox.oldest_undelivered() is None


async def test_failed_delivery_backs_off_exponentially_up_to_the_cap(outbox, clock):
    channel = FakeChannel("failed")
    outbox.queue_notification("e1", "telegram", "hot")
    delays = []

    await outbox.deliver({"telegram": channel})
    for _ in range(5):
        before = len(channel.sent)
        waited = 0.0
        while len(channel.sent) == before:
            clock.advance(1)
            waited += 1
            await outbox.deliver({"telegram": channel})
        delays.append(waited)

    assert delays == [10.0, 20.0, 40.0, 40.0, 40.0]


async def test_unknown_outcome_is_kept_and_retried_until_accepted(outbox, clock):
    channel = FakeChannel("unknown", "accepted")
    outbox.queue_notification("e1", "telegram", "hot")

    await outbox.deliver({"telegram": channel})
    assert outbox.status("e1", "telegram") == "unknown"
    assert outbox.oldest_undelivered() is not None

    assert await outbox.deliver({"telegram": channel}) == 0  # still backing off
    clock.advance(BASE)
    assert await outbox.deliver({"telegram": channel}) == 1

    assert outbox.status("e1", "telegram") == "accepted"
    assert outbox.results("e1", "telegram") == ("unknown", "accepted")
    assert channel.sent == ["hot", "hot"]  # a duplicate message is the accepted cost


async def test_channel_exception_counts_as_unknown(outbox):
    outbox.queue_notification("e1", "telegram", "hot")

    await outbox.deliver({"telegram": FakeChannel(RuntimeError("socket closed"))})

    assert outbox.status("e1", "telegram") == "unknown"


async def test_channels_are_independent(outbox, clock):
    telegram, email = FakeChannel("accepted"), FakeChannel("failed", "accepted")
    outbox.queue_notification("e1", "telegram", "hot")
    outbox.queue_notification("e1", "email", "hot")

    await outbox.deliver({"telegram": telegram, "email": email})
    clock.advance(BASE)
    await outbox.deliver({"telegram": telegram, "email": email})

    assert len(telegram.sent) == 1
    assert len(email.sent) == 2
    assert outbox.status("e1", "email") == "accepted"


async def test_unconfigured_channel_is_left_pending(outbox):
    outbox.queue_notification("e1", "sms", "hot")

    assert await outbox.deliver({"telegram": FakeChannel("accepted")}) == 0

    assert outbox.status("e1", "sms") == "pending"
    assert outbox.oldest_undelivered() is not None


async def test_attempts_stop_at_the_configured_limit(db, clock):
    limited = Outbox(db, clock, base_seconds=BASE, cap_seconds=CAP, max_attempts=2)
    channel = FakeChannel("failed")
    limited.queue_notification("e1", "telegram", "hot")

    for _ in range(5):
        await limited.deliver({"telegram": channel})
        clock.advance(CAP)

    assert len(channel.sent) == 2
    assert limited.oldest_undelivered() is not None  # still reported as undelivered


async def test_queue_survives_a_new_outbox_on_the_same_database(db, clock, outbox):
    outbox.queue_notification("e1", "telegram", "hot")
    channel = FakeChannel("accepted")

    reopened = Outbox(db, clock, base_seconds=BASE, cap_seconds=CAP)

    assert await reopened.deliver({"telegram": channel}) == 1
    assert reopened.oldest_undelivered() is None


def test_oldest_undelivered_is_the_creation_time_of_the_oldest(outbox, clock):
    assert outbox.oldest_undelivered() is None
    first = clock.now()
    outbox.queue_notification("e1", "telegram", "a")
    clock.advance(100)
    outbox.queue_notification("e2", "telegram", "b")

    assert outbox.oldest_undelivered() == first


def test_oldest_undelivered_can_be_limited_to_channels_that_have_a_sender(outbox, clock):
    outbox.queue_notification("e1", "sms", "a")
    clock.advance(100)
    second = clock.now()
    outbox.queue_notification("e2", "telegram", "b")

    assert outbox.oldest_undelivered(["telegram", "email"]) == second
    assert outbox.oldest_undelivered([]) is None


async def test_channel_exception_is_logged_by_type_without_its_message(outbox, caplog):
    outbox.queue_notification("e1", "telegram", "hot")

    with caplog.at_level(logging.WARNING, logger="growbridge.observer.outbox"):
        await outbox.deliver({"telegram": FakeChannel(RuntimeError("secret-token-xyz"))})

    assert "RuntimeError" in caplog.text
    assert "secret-token-xyz" not in caplog.text


async def test_backoff_exponent_is_capped_so_it_cannot_overflow(db, clock):
    big = Outbox(db, clock, base_seconds=BASE, cap_seconds=CAP, max_attempts=10_000)
    big.queue_notification("e1", "telegram", "hot")
    db.execute("UPDATE observer_outbox SET attempts = 5000")

    await big.deliver({"telegram": FakeChannel("failed")})

    row = db.one("SELECT attempts, next_at FROM observer_outbox")
    assert row["attempts"] == 5001
    assert row["next_at"] == clock.now() + CAP
